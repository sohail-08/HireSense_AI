"""Single-submission exercises, LLM correctness scoring and human approval."""
import asyncio
import copy
import json
from datetime import datetime, timedelta, timezone
from uuid import uuid4
from sqlalchemy import select, delete
from app.agents.interview_analysis import digest
from app.agents.work_sample import WorkSampleGraph
from app.agents.practical_scoring import POLICY as GRADING_POLICY, PROMPT_VERSION, PracticalScorer, result_hash
from app.config import get_settings
from app.llm.errors import failure_detail
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


def approved_score(assessment):
    if not assessment or assessment.status != "approved" or assessment.snapshot.get("policy") != GRADING_POLICY:
        return None
    result = assessment.approved_result
    if (not result or result != assessment.result or not result.get("verified") or result.get("score") is None
            or not assessment.approved_by or not assessment.approved_at):
        return None
    return {**copy.deepcopy(result), "assessment_id": assessment.id, "policy": GRADING_POLICY,
        "exercise_id": assessment.snapshot["exercise_id"], "task_hash": assessment.snapshot["task_hash"],
        "submission_hash": assessment.snapshot["submission_hash"], "result_hash": result_hash(assessment.snapshot, result),
        "model": assessment.snapshot["model"], "prompt_version": assessment.snapshot["prompt_version"], "findings": [],
        "approved_by": assessment.approved_by, "approved_at": utc(assessment.approved_at).isoformat()}

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

    def finish(self, db, exercise, attempt, status):
        if attempt.deadline_at:
            attempt.remaining_seconds = max(0, int((utc(attempt.deadline_at) - self.now()).total_seconds()))
        attempt.status, exercise.status = status, status
        attempt.finished_at = self.now()
        attempt.submission_hash = digest({"task_hash": exercise.task_hash, "attempt": attempt.number,
            "content": attempt.content, "explanation": attempt.explanation, "status": status})
        self.event(exercise, status, "candidate" if status == "submitted" else "system")
        if exercise.grading_policy == GRADING_POLICY:
            self.queue_assessment(db, exercise, attempt)

    def reconcile(self, db, row, exercise):
        if not exercise:
            return
        attempts = self.attempts(db, exercise)
        if not attempts:
            return
        attempt = attempts[-1]
        if attempt.status not in FINISHED and row.room_status in {"ending", "ended", "cancelled"}:
            self.finish(db, exercise, attempt, "interview_ended")
        elif attempt.status == "running" and attempt.deadline_at and utc(attempt.deadline_at) <= self.now():
            self.finish(db, exercise, attempt, "time_ended")

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
            assessment = db.scalar(select(WorkSampleAssessment).where(WorkSampleAssessment.attempt_id == attempts[-1].id)) if attempts else None
            current = None
            if assessment and assessment.snapshot.get("policy") == GRADING_POLICY:
                current = {"id": assessment.id, "status": assessment.status, "result": assessment.result,
                    "result_hash": result_hash(assessment.snapshot, assessment.result) if assessment.result else None,
                    "submission_hash": assessment.snapshot["submission_hash"], "error": assessment.error,
                    "approved_at": utc(assessment.approved_at).isoformat() if assessment.approved_at else None, "approved_by": assessment.approved_by}
            result.update(interview_id=exercise.interview_id, events=exercise.events, decision=decision_result(decision), assessment=current)
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
        exercise.grading_policy = GRADING_POLICY
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
            exercise.grading_policy = GRADING_POLICY
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
            self.finish(db, exercise, attempt, "submitted")
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

    def queue_assessment(self, db, exercise, attempt):
        existing = db.scalar(select(WorkSampleAssessment).where(WorkSampleAssessment.attempt_id == attempt.id))
        if existing:
            if existing.snapshot.get("policy") != GRADING_POLICY:
                raise RoomConflict("This historical assessment is preserved. Automatic scoring applies to new exercises.")
            return existing
        assessment = WorkSampleAssessment(attempt_id=attempt.id, status="queued", result={}, snapshot={
            "policy": GRADING_POLICY, "prompt_version": PROMPT_VERSION, "model": get_settings().gemini_chat_model,
            "request_id": uuid4().hex, "exercise_id": exercise.id, "task_hash": exercise.task_hash,
            "submission_hash": attempt.submission_hash, "task": public_task(exercise.task), "content": attempt.content,
            "status": attempt.status})
        db.add(assessment)
        db.flush()
        self.event(exercise, "scoring_queued", "system")
        return assessment

    def score(self, db, user_id, interview_id, request):
        row = self.rooms.owned(db, user_id, interview_id, lock=True)
        exercise = self.exercise(db, row.id)
        if not exercise or utc(exercise.expires_at) <= self.now():
            raise LookupError("Exercise not found or expired")
        self.reconcile(db, row, exercise)
        attempts = self.attempts(db, exercise)
        if not attempts or attempts[-1].status not in FINISHED:
            raise RoomConflict("Wait for the candidate's work to finish before scoring.")
        attempt = attempts[-1]
        if request.submission_hash != attempt.submission_hash:
            raise RoomConflict("The saved submission changed. Reload it before scoring.")
        exercise.grading_policy = GRADING_POLICY
        assessment = self.queue_assessment(db, exercise, attempt)
        if assessment.status in {"failed", "needs_verification", "cancelled"}:
            assessment.status, assessment.result, assessment.error = "queued", {}, None
            assessment.snapshot = {**assessment.snapshot, "request_id": uuid4().hex}
            self.event(exercise, "scoring_retry_requested", f"interviewer:{user_id}")
        # Scored/approved work is stable: repeated clicks never reroll an accepted score.
        db.commit()
        return self.present(db, exercise)

    @staticmethod
    def bound(exercise, attempt, snapshot):
        return (snapshot.get("policy") == GRADING_POLICY and snapshot.get("exercise_id") == exercise.id
            and snapshot.get("task_hash") == exercise.task_hash and digest(exercise.task) == exercise.task_hash
            and snapshot.get("submission_hash") == attempt.submission_hash
            and snapshot.get("content") == attempt.content and snapshot.get("status") == attempt.status
            and snapshot.get("task") == public_task(exercise.task) and attempt.status in FINISHED
            and attempt.submission_hash == digest({"task_hash": exercise.task_hash, "attempt": attempt.number,
                "content": attempt.content, "explanation": attempt.explanation, "status": attempt.status}))

    def approve(self, db, user_id, interview_id, request):
        row = self.rooms.owned(db, user_id, interview_id, lock=True)
        exercise = self.exercise(db, row.id)
        if not exercise or utc(exercise.expires_at) <= self.now():
            raise LookupError("Exercise not found or expired")
        attempts = self.attempts(db, exercise)
        assessment = db.get(WorkSampleAssessment, request.assessment_id, populate_existing=True)
        if not attempts or not assessment or assessment.attempt_id != attempts[-1].id:
            raise RoomConflict("Reload the assessment for this submission.")
        attempt = attempts[-1]
        if (not self.bound(exercise, attempt, assessment.snapshot) or request.submission_hash != attempt.submission_hash
                or request.result_hash != result_hash(assessment.snapshot, assessment.result)):
            raise RoomConflict("The saved assessment changed. Reload before approving.")
        if assessment.status == "approved":
            return self.present(db, exercise)
        result = assessment.result
        if assessment.status != "scored" or not result.get("verified") or type(result.get("score")) is not int or not 0 <= result["score"] <= 100:
            raise RoomConflict("Only a verified LLM score can be approved.")
        assessment.approved_result = copy.deepcopy(result)
        assessment.approved_by, assessment.approved_at, assessment.status = user_id, self.now(), "approved"
        self.event(exercise, "llm_score_approved", f"interviewer:{user_id}")
        db.commit()
        return self.present(db, exercise)

    def job(self, db, assessment_id):
        initial = db.get(WorkSampleAssessment, assessment_id)
        attempt = db.get(WorkSampleAttempt, initial.attempt_id) if initial else None
        parent = db.get(WorkSampleExercise, attempt.exercise_id) if attempt else None
        if not parent:
            return None
        # Use the same parent-first lock order as candidate saves and interview shutdown.
        row = db.scalar(select(InterviewSchedule).where(InterviewSchedule.id == parent.interview_id).with_for_update())
        if not row:
            return None
        exercise = self.exercise(db, row.id)
        assessment = db.get(WorkSampleAssessment, assessment_id, populate_existing=True)
        attempts = self.attempts(db, exercise) if exercise else []
        if not assessment or not attempts or attempts[-1].id != assessment.attempt_id:
            return None
        return exercise, attempts[-1], assessment

    def process(self, assessment_id):
        with self.factory() as db:
            job = self.job(db, assessment_id)
            if not job:
                return
            exercise, attempt, assessment = job
            if assessment.status != "queued" or assessment.snapshot.get("policy") != GRADING_POLICY:
                return
            if utc(exercise.expires_at) <= self.now() or not self.bound(exercise, attempt, assessment.snapshot):
                assessment.status, assessment.error = "cancelled", "The saved work is no longer available for this assessment."
                db.commit()
                return
            snapshot = copy.deepcopy(assessment.snapshot)
            assessment.status, assessment.error = "processing", None
            db.commit()
        try:
            result = PracticalScorer(self.model).evaluate(snapshot)
            status, error = ("scored" if result["verified"] and result["score"] is not None else "needs_verification"), None
        except Exception as exc:
            # Do not leak provider messages, private submissions or credentials to logs/UI.
            failure = failure_detail(exc)
            result, status, error = {"failure": failure}, "failed", failure["message"]
        with self.factory() as db:
            job = self.job(db, assessment_id)
            if not job:
                return
            exercise, attempt, assessment = job
            if assessment.status != "processing" or assessment.snapshot.get("request_id") != snapshot["request_id"]:
                return
            if utc(exercise.expires_at) <= self.now() or not self.bound(exercise, attempt, snapshot):
                assessment.status, assessment.error = "cancelled", "The saved work changed or expired during scoring."
            else:
                assessment.result, assessment.status, assessment.error = result, status, error
            db.commit()

    @staticmethod
    def recover(db):
        for assessment in db.scalars(select(WorkSampleAssessment).where(WorkSampleAssessment.status.in_(["queued", "processing"]))):
            if assessment.snapshot.get("policy") == GRADING_POLICY:
                if assessment.status == "processing":
                    assessment.snapshot = {**assessment.snapshot, "request_id": uuid4().hex}
                assessment.status = "queued"
            else:
                assessment.status, assessment.error = "cancelled", "This historical grading request is no longer active."
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
            pending = next((a.id for a in db.scalars(select(WorkSampleAssessment).where(WorkSampleAssessment.status == "queued").order_by(WorkSampleAssessment.id))
                if a.snapshot.get("policy") == GRADING_POLICY), None)
        if pending is not None:
            self.process(pending)

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
            scored = db.scalar(select(WorkSampleAssessment).where(WorkSampleAssessment.attempt_id == attempt.id))
            assessment = (approved_score(scored) if scored and WorkSampleService.bound(exercise, attempt, scored.snapshot) else None) or decision_result(decision)
            result.append({"interview_id": exercise.interview_id, "exercise_id": exercise.id, "title": exercise.task["title"],
                "task": public_task(exercise.task), "task_hash": exercise.task_hash, "status": attempt.status,
                "content": attempt.content, "submission_hash": attempt.submission_hash,
                "review_status": "reviewed" if assessment else "not_reviewed", "assessment": assessment,
                "approved_by": assessment["approved_by"] if assessment else None,
                "approved_at": assessment["approved_at"] if assessment else None,
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
