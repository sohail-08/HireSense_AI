"""Single-submission exercises with immutable interviewer-only correctness decisions."""
import asyncio
import copy
import json
from datetime import datetime, timedelta, timezone
from uuid import uuid4
from sqlalchemy import select, update, delete
from app.agents.interview_analysis import digest
from app.agents.work_sample import WorkSampleGraph
from app.config import get_settings
from app.database import SessionLocal
from app.models.interview import InterviewSchedule
from app.models.job import JobDescription, JobPosting
from app.models.work_sample import WorkSampleTemplate, WorkSampleExercise, WorkSampleAttempt, WorkSampleAssessment, WorkSampleDecision
from app.schemas.work_sample import Task
from app.services.interview_content import utc
from app.services.interview_rooms import InterviewRooms, RoomConflict, RoomAccessError

FINISHED = {"submitted", "time_ended", "interview_ended"}
OPEN = {"shared", "ready", "running", "paused"}
DECISION_POLICY = "interviewer-correctness-binary-v1"

def now():
    return datetime.now(timezone.utc)

def public_task(task):
    # Legacy rubrics remain stored for audit but are not part of the new interface.
    result = {key: copy.deepcopy(task.get(key, "")) for key in Task.model_fields}
    result["duration_minutes"] = min(15, max(1, int(task.get("duration_minutes", 15))))
    return result

def decision_result(decision):
    if not decision:
        return None
    return {"decision_id": decision.id, "policy": DECISION_POLICY, "exercise_id": decision.exercise_id,
        "submission_hash": decision.submission_hash, "correct": decision.correct,
        "score": 100 if decision.correct else 0, "findings": [],
        "summary": decision.note or ("Correctness approved by the interviewer." if decision.correct else "Correctness not approved by the interviewer."),
        "approved_by": decision.decided_by, "approved_at": utc(decision.decided_at).isoformat()}

class WorkSampleService:
    def __init__(self, rooms=None, model=None, session_factory=None, knowledge=None):
        self.rooms = rooms or InterviewRooms()
        self.now = self.rooms.now
        self.model, self.knowledge = model, knowledge
        self.factory = session_factory or SessionLocal

    @staticmethod
    def exercise(db, interview_id):
        return db.scalar(select(WorkSampleExercise).where(WorkSampleExercise.interview_id == interview_id)
            .with_for_update().execution_options(populate_existing=True))

    @staticmethod
    def attempts(db, exercise):
        return list(db.scalars(select(WorkSampleAttempt).where(WorkSampleAttempt.exercise_id == exercise.id)
            .order_by(WorkSampleAttempt.number).execution_options(populate_existing=True)))

    def event(self, exercise, kind, actor, reason=""):
        exercise.events = [*(exercise.events or []), {"kind": kind, "actor": actor, "reason": reason, "at": self.now().isoformat()}]
        exercise.version += 1

    def finish(self, exercise, attempt, status):
        if attempt.deadline_at:
            attempt.remaining_seconds = max(0, int((utc(attempt.deadline_at) - self.now()).total_seconds()))
        attempt.status, exercise.status = status, status
        attempt.finished_at = self.now()
        attempt.submission_hash = digest({"task_hash": exercise.task_hash, "attempt": attempt.number,
            "content": attempt.content, "explanation": attempt.explanation, "status": status})
        self.event(exercise, status, "candidate" if status == "submitted" else "system")

    def reconcile(self, db, row, exercise):
        if not exercise:
            return
        attempts = self.attempts(db, exercise)
        if not attempts:
            return
        attempt = attempts[-1]
        if attempt.status not in FINISHED and row.room_status in {"ending", "ended", "cancelled"}:
            self.finish(exercise, attempt, "interview_ended")
        elif attempt.status == "running" and attempt.deadline_at and utc(attempt.deadline_at) <= self.now():
            self.finish(exercise, attempt, "time_ended")

    @staticmethod
    def attempt_data(attempt):
        return {key: getattr(attempt, key) for key in ("id", "status", "content", "revision",
            "remaining_seconds", "deadline_at", "started_at", "saved_at", "finished_at", "submission_hash")}

    def present(self, db, exercise, *, candidate=False):
        if not exercise or (candidate and exercise.status == "draft"):
            return {"exercise": None, "server_now": self.now()}
        attempts = self.attempts(db, exercise)
        result = {"id": exercise.id, "task": public_task(exercise.task), "task_hash": exercise.task_hash,
            "status": exercise.status, "version": exercise.version, "approved_at": exercise.approved_at,
            "attempt": self.attempt_data(attempts[-1]) if attempts else None}
        if not candidate:
            decision = db.scalar(select(WorkSampleDecision).where(WorkSampleDecision.exercise_id == exercise.id))
            result.update(interview_id=exercise.interview_id, events=exercise.events, decision=decision_result(decision))
        return {"exercise": result, "server_now": self.now()}

    def read(self, db, user_id, interview_id):
        row = self.rooms.owned(db, user_id, interview_id, lock=True)
        exercise = self.exercise(db, row.id)
        if exercise and utc(exercise.expires_at) <= self.now():
            return {"exercise": None, "server_now": self.now()}
        self.reconcile(db, row, exercise)
        db.commit()
        return self.present(db, exercise)

    def candidate_context(self, db, token):
        row = self.rooms.session(db, token, lock=True)
        if not row.candidate_admitted_at:
            raise RoomAccessError("not_admitted", 403)
        exercise = self.exercise(db, row.id)
        if exercise and utc(exercise.expires_at) <= self.now():
            raise RoomAccessError("exercise_expired", 410)
        self.reconcile(db, row, exercise)
        if exercise and exercise.status in FINISHED:
            db.commit()
        return row, exercise

    def candidate_read(self, db, token):
        _, exercise = self.candidate_context(db, token)
        db.commit()
        return self.present(db, exercise, candidate=True)

    def save_task(self, db, user_id, interview_id, request, *, commit=True):
        row = self.rooms.owned(db, user_id, interview_id, lock=True)
        self.rooms.usable(db, row, link=False)
        exercise = self.exercise(db, row.id)
        if exercise and (exercise.status != "draft" or exercise.version != request.version):
            raise RoomConflict("This task changed or was shared. Refresh before editing.")
        if not exercise:
            if request.version != 0:
                raise RoomConflict("Refresh the exercise before saving.")
            exercise = WorkSampleExercise(interview_id=row.id, application_id=row.application_id, owner_id=user_id,
                task={}, task_hash="", status="draft", version=0, events=[],
                expires_at=self.now() + timedelta(days=get_settings().work_sample_retention_days))
            db.add(exercise)
        exercise.task = request.task.model_dump()
        exercise.task_hash = digest(exercise.task)
        self.event(exercise, "task_saved", f"interviewer:{user_id}")
        if commit:
            db.commit()
        else:
            db.flush()
        return self.present(db, exercise)

    def action(self, db, user_id, interview_id, request):
        row = self.rooms.owned(db, user_id, interview_id, lock=True)
        self.rooms.usable(db, row, link=False)
        exercise = self.exercise(db, row.id)
        if not exercise or utc(exercise.expires_at) <= self.now():
            raise LookupError("Exercise not found or expired")
        self.reconcile(db, row, exercise)
        if request.version != exercise.version:
            db.commit()
            raise RoomConflict("Exercise state changed. Refresh and try again.")
        if len(exercise.events) >= 500:
            raise RoomConflict("Exercise action limit reached.")
        attempts = self.attempts(db, exercise)
        attempt = attempts[-1] if attempts else None
        if request.action == "share" and exercise.status == "draft" and not attempts:
            task = Task.model_validate(public_task(exercise.task))
            exercise.approved_at, exercise.status = self.now(), "shared"
            db.add(WorkSampleAttempt(exercise_id=exercise.id, number=1, status="shared", content="", explanation="",
                remaining_seconds=task.duration_minutes * 60))
        elif request.action == "start" and attempt and attempt.status == "ready":
            if not row.candidate_admitted_at:
                raise RoomConflict("Admit the candidate before starting the exercise.")
            attempt.remaining_seconds = min(attempt.remaining_seconds, 900)
            attempt.started_at = self.now()
            attempt.status = exercise.status = "running"
            attempt.deadline_at = self.now() + timedelta(seconds=attempt.remaining_seconds)
        elif request.action == "pause" and attempt and attempt.status == "running":
            if len(request.reason.strip()) < 5:
                raise RoomConflict("Enter a reason for pausing the exercise.")
            attempt.remaining_seconds = min(900, max(0, int((utc(attempt.deadline_at) - self.now()).total_seconds())))
            attempt.deadline_at = None
            attempt.status = exercise.status = "paused"
        elif request.action == "resume" and attempt and attempt.status == "paused":
            attempt.remaining_seconds = min(attempt.remaining_seconds, 900)
            attempt.status = exercise.status = "running"
            attempt.deadline_at = self.now() + timedelta(seconds=attempt.remaining_seconds)
        else:
            raise RoomConflict("This action is unavailable. Each candidate has one submission only.")
        self.event(exercise, request.action, f"interviewer:{user_id}", request.reason)
        db.commit()
        return self.present(db, exercise)

    def ready(self, db, token, request):
        _, exercise = self.candidate_context(db, token)
        attempt = self.attempts(db, exercise)[-1] if exercise and exercise.status != "draft" else None
        if not attempt or attempt.id != request.attempt_id or attempt.status not in {"shared", "ready"}:
            raise RoomConflict("This exercise is not waiting for readiness.")
        if attempt.status == "shared":
            attempt.status = exercise.status = "ready"
            self.event(exercise, "candidate_ready", "candidate")
        db.commit()
        return self.present(db, exercise, candidate=True)

    def save_submission(self, db, token, request):
        _, exercise = self.candidate_context(db, token)
        attempt = self.attempts(db, exercise)[-1] if exercise and exercise.status != "draft" else None
        if not attempt or attempt.id != request.attempt_id:
            raise RoomConflict("This submission is no longer active. Refresh to recover your work.")
        if attempt.status == "submitted" and request.submit and request.content == attempt.content:
            return self.present(db, exercise, candidate=True)
        if attempt.status != "running":
            raise RoomConflict("The exercise is not running. Your last saved work is preserved.")
        if request.revision != attempt.revision:
            raise RoomConflict("This work changed in another tab. Refresh before saving; keep a copy of your unsaved text.")
        attempt.content = request.content
        attempt.revision += 1
        attempt.saved_at = self.now()
        if request.submit:
            self.finish(exercise, attempt, "submitted")
        db.commit()
        return self.present(db, exercise, candidate=True)

    def list_templates(self, db, user_id):
        return [{"id": row.id, "task": public_task(row.task)} for row in db.scalars(select(WorkSampleTemplate).where(
            WorkSampleTemplate.owner_id == user_id).order_by(WorkSampleTemplate.id.desc()).limit(100))]

    def template(self, db, user_id, task):
        row = WorkSampleTemplate(owner_id=user_id, task=task.model_dump())
        db.add(row)
        db.commit()
        return {"id": row.id, "task": row.task}

    def task_context(self, db, user_id, interview_id, brief):
        row = self.rooms.owned(db, user_id, interview_id, lock=True)
        self.rooms.usable(db, row, link=False)
        exercise = self.exercise(db, row.id)
        if exercise and exercise.status != "draft":
            raise RoomConflict("A task has already been shared. The candidate has only one submission.")
        posting = db.get(JobPosting, row.job_posting_id)
        job = db.get(JobDescription, posting.job_description_id)
        context = {"job_title": job.title, "job_description": job.content[:16000], "knowledge": []}
        version, job_hash = exercise.version if exercise else 0, digest([job.title, job.content])
        db.rollback()
        try:
            from app.rag.service import KnowledgeBaseService
            from app.rag.embeddings import OllamaEmbeddingProvider
            knowledge = self.knowledge or KnowledgeBaseService(OllamaEmbeddingProvider())
            chunks = knowledge.search(db, f"{job.title} {brief}"[:5000], top_k=4, min_score=.25)
            context["knowledge"] = [{"title": c.document_title, "excerpt": c.content[:4000]} for c in chunks]
        except Exception:
            context["knowledge_unavailable"] = True
        finally:
            db.rollback()
        return context, version, job_hash

    def suggest_tasks(self, db, user_id, interview_id, brief):
        context, version, job_hash = self.task_context(db, user_id, interview_id, brief)
        options = WorkSampleGraph(self.model).suggest(context, brief)
        return [{**option, "id": uuid4().hex, "job_hash": job_hash, "exercise_version": version} for option in options]

    def create_selected_task(self, db, user_id, interview_id, option):
        from app.schemas.work_sample import SaveTask
        context, _, job_hash = self.task_context(db, user_id, interview_id, option["summary"])
        if job_hash != option["job_hash"]:
            raise RoomConflict("The job posting changed. Ask for new task suggestions.")
        task = Task.model_validate(WorkSampleGraph(self.model).draft(context, json.dumps(option)))
        # The model cannot enlarge the time approved by the user's selected suggestion.
        task.duration_minutes = option["duration_minutes"]
        row = self.rooms.owned(db, user_id, interview_id, lock=True)
        posting = db.get(JobPosting, row.job_posting_id)
        job = db.get(JobDescription, posting.job_description_id)
        if digest([job.title, job.content]) != job_hash:
            raise RoomConflict("The job posting changed. Ask for new task suggestions.")
        return SaveTask(task=task, version=option["exercise_version"])

    def decide(self, db, user_id, interview_id, request):
        row = self.rooms.owned(db, user_id, interview_id, lock=True)
        exercise = self.exercise(db, row.id)
        if not exercise or utc(exercise.expires_at) <= self.now():
            raise LookupError("Exercise not found or expired")
        self.reconcile(db, row, exercise)
        attempts = self.attempts(db, exercise)
        if not attempts or attempts[-1].status not in FINISHED:
            raise RoomConflict("Wait for the candidate's work to finish before deciding correctness.")
        attempt = attempts[-1]
        if request.submission_hash != attempt.submission_hash:
            raise RoomConflict("The saved submission changed. Reload it before deciding.")
        previous = db.scalar(select(WorkSampleDecision).where(WorkSampleDecision.exercise_id == exercise.id))
        if previous:
            if previous.submission_hash == request.submission_hash and previous.correct == request.correct:
                return self.present(db, exercise)
            raise RoomConflict("This correctness decision is already final.")
        db.add(WorkSampleDecision(exercise_id=exercise.id, attempt_id=attempt.id, submission_hash=attempt.submission_hash,
            correct=request.correct, note=request.note, decided_by=user_id, decided_at=self.now()))
        self.event(exercise, "correctness_approved" if request.correct else "correctness_rejected", f"interviewer:{user_id}", request.note)
        db.commit()
        return self.present(db, exercise)

    @staticmethod
    def recover(db):
        # Stop legacy automatic grading; keep all existing reviews and submissions.
        db.execute(update(WorkSampleAssessment).where(WorkSampleAssessment.status.in_(["queued", "processing"]))
            .values(status="cancelled", error="Practical correctness is now decided by the interviewer."))
        db.commit()

    @staticmethod
    def delete_for_interviews(db, ids):
        exercise_ids = select(WorkSampleExercise.id).where(WorkSampleExercise.interview_id.in_(ids))
        attempt_ids = select(WorkSampleAttempt.id).where(WorkSampleAttempt.exercise_id.in_(exercise_ids))
        db.execute(delete(WorkSampleDecision).where(WorkSampleDecision.exercise_id.in_(exercise_ids)))
        db.execute(delete(WorkSampleAssessment).where(WorkSampleAssessment.attempt_id.in_(attempt_ids)))
        db.execute(delete(WorkSampleAttempt).where(WorkSampleAttempt.exercise_id.in_(exercise_ids)))
        db.execute(delete(WorkSampleExercise).where(WorkSampleExercise.interview_id.in_(ids)))

    @staticmethod
    def delete_discussion_sources(db, ids):
        attempts = select(WorkSampleAttempt.id).join(WorkSampleExercise).where(WorkSampleExercise.interview_id.in_(ids))
        for assessment in db.scalars(select(WorkSampleAssessment).where(WorkSampleAssessment.attempt_id.in_(attempts))):
            if assessment.snapshot.get("discussion"):
                db.delete(assessment)

    def tick(self):
        with self.factory() as db:
            expired = list(db.scalars(select(WorkSampleExercise.interview_id).where(WorkSampleExercise.expires_at <= self.now())))
            if expired:
                from app.services.assessment_service import AssessmentService
                AssessmentService.delete_sources(db, interview_ids=expired)
                self.delete_for_interviews(db, expired)
                db.commit()
            ids = list(db.scalars(select(WorkSampleExercise.interview_id).where(WorkSampleExercise.status.in_(OPEN))))
            for interview_id in ids:
                row = db.scalar(select(InterviewSchedule).where(InterviewSchedule.id == interview_id).with_for_update())
                if row:
                    self.reconcile(db, row, self.exercise(db, interview_id))
                db.commit()

    @staticmethod
    def report_sources(db, user_id, application_id):
        result = []
        for exercise in db.scalars(select(WorkSampleExercise).where(WorkSampleExercise.application_id == application_id,
                WorkSampleExercise.owner_id == user_id, WorkSampleExercise.expires_at > now()).order_by(WorkSampleExercise.id)):
            attempts = list(db.scalars(select(WorkSampleAttempt).where(WorkSampleAttempt.exercise_id == exercise.id).order_by(WorkSampleAttempt.number)))
            if not attempts or attempts[-1].status not in FINISHED:
                continue
            attempt = attempts[-1]
            decision = db.scalar(select(WorkSampleDecision).where(WorkSampleDecision.exercise_id == exercise.id))
            assessment = decision_result(decision)
            result.append({"interview_id": exercise.interview_id, "exercise_id": exercise.id, "title": exercise.task["title"],
                "task": public_task(exercise.task), "task_hash": exercise.task_hash, "status": attempt.status,
                "content": attempt.content, "submission_hash": attempt.submission_hash,
                "review_status": "reviewed" if decision else "not_reviewed", "assessment": assessment,
                "approved_by": decision.decided_by if decision else None,
                "approved_at": utc(decision.decided_at).isoformat() if decision else None,
                "expires_at": utc(exercise.expires_at).isoformat()})
        return copy.deepcopy(result)

async def work_sample_worker(stop):
    import logging
    while not stop.is_set():
        try:
            await asyncio.to_thread(WorkSampleService().tick)
        except Exception:
            logging.getLogger(__name__).warning("Practical exercise worker will retry its next tick")
        try:
            await asyncio.wait_for(stop.wait(), timeout=3)
        except TimeoutError:
            pass
