"""Live exercise lifecycle. Lock order: interview, exercise, attempt, assessment.

Candidate authorization always comes from the existing scoped interview cookie.
No email-based application matching, code execution, or automatic hiring decisions.
"""
import asyncio
import copy
from datetime import datetime, timedelta, timezone
from sqlalchemy import select, update, delete
from app.agents.interview_analysis import digest
from app.agents.work_sample import WorkSampleGraph, PROMPT_VERSION
from app.config import get_settings
from app.database import SessionLocal
from app.models.interview import InterviewSchedule
from app.models.job import JobDescription, JobPosting
from app.models.work_sample import WorkSampleTemplate, WorkSampleExercise, WorkSampleAttempt, WorkSampleAssessment
from app.schemas.work_sample import Task, Evaluation, validated_evaluation
from app.services.interview_content import utc
from app.services.interview_rooms import InterviewRooms, RoomConflict, RoomAccessError

FINISHED = {"submitted", "time_ended", "interview_ended"}
OPEN = {"shared", "ready", "running", "paused"}


def now():
    return datetime.now(timezone.utc)


class WorkSampleService:
    def __init__(self, rooms=None, model=None, session_factory=None):
        self.rooms = rooms or InterviewRooms()
        self.now = self.rooms.now
        self.model = model
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
        exercise.events = [*(exercise.events or []), {"kind": kind, "actor": actor, "reason": reason,
                                                     "at": self.now().isoformat()}]
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
        return {key: getattr(attempt, key) for key in ("id", "number", "status", "content", "explanation", "revision",
            "remaining_seconds", "deadline_at", "started_at", "saved_at", "finished_at", "submission_hash")}

    def present(self, db, exercise, *, candidate=False):
        if not exercise or (candidate and exercise.status == "draft"):
            return {"exercise": None, "server_now": self.now()}
        attempts = self.attempts(db, exercise)
        result = {"id": exercise.id, "task": copy.deepcopy(exercise.task), "task_hash": exercise.task_hash,
            "status": exercise.status, "version": exercise.version, "approved_at": exercise.approved_at,
            "attempt": self.attempt_data(attempts[-1]) if attempts else None}
        if not candidate:
            result.update(interview_id=exercise.interview_id, events=exercise.events,
                          attempts=[self.attempt_data(a) for a in attempts], assessments=[])
            for assessment in db.scalars(select(WorkSampleAssessment).where(
                    WorkSampleAssessment.attempt_id.in_([a.id for a in attempts])).order_by(WorkSampleAssessment.id)):
                result["assessments"].append({key: getattr(assessment, key) for key in ("id", "attempt_id", "status",
                    "result", "approved_result", "review_reason", "approved_by", "approved_at", "error")})
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
        # Expiry is durable even if a following late save is rejected.
        if exercise and exercise.status in FINISHED:
            db.commit()
        return row, exercise

    def candidate_read(self, db, token):
        _, exercise = self.candidate_context(db, token)
        db.commit()
        return self.present(db, exercise, candidate=True)

    def save_task(self, db, user_id, interview_id, request):
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
        db.commit()
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
        action = request.action
        if action == "share" and exercise.status == "draft":
            Task.model_validate(exercise.task)
            exercise.approved_at, exercise.status = self.now(), "shared"
            db.add(WorkSampleAttempt(exercise_id=exercise.id, number=1, status="shared", content="", explanation="",
                                    remaining_seconds=exercise.task["duration_minutes"] * 60))
        elif action == "start" and attempt and attempt.status == "ready":
            if not row.candidate_admitted_at:
                raise RoomConflict("Admit the candidate before starting the exercise.")
            attempt.started_at = self.now()
            attempt.status = exercise.status = "running"
            attempt.deadline_at = self.now() + timedelta(seconds=attempt.remaining_seconds)
        elif action == "pause" and attempt and attempt.status == "running":
            if len(request.reason.strip()) < 5:
                raise ValueError("Enter a reason for the timing adjustment")
            attempt.remaining_seconds = max(0, int((utc(attempt.deadline_at) - self.now()).total_seconds()))
            attempt.deadline_at = None
            attempt.status = exercise.status = "paused"
        elif action == "resume" and attempt and attempt.status == "paused":
            attempt.status = exercise.status = "running"
            attempt.deadline_at = self.now() + timedelta(seconds=attempt.remaining_seconds)
        elif action == "extend" and attempt and attempt.status in {"running", "paused"}:
            if len(request.reason.strip()) < 5:
                raise ValueError("Enter a reason for the timing adjustment")
            seconds = request.extra_minutes * 60
            if attempt.remaining_seconds + seconds > 14400:
                raise ValueError("Exercise duration exceeds four hours")
            attempt.remaining_seconds += seconds
            if attempt.deadline_at:
                attempt.deadline_at = utc(attempt.deadline_at) + timedelta(seconds=seconds)
        elif action == "retry" and attempt and attempt.status in FINISHED:
            if len(request.reason.strip()) < 5:
                raise ValueError("Enter a reason for the additional attempt")
            if attempt.number >= 5:
                raise RoomConflict("This exercise has reached its five-attempt limit.")
            exercise.status = "shared"
            db.add(WorkSampleAttempt(exercise_id=exercise.id, number=attempt.number + 1, status="shared",
                content=attempt.content, explanation=attempt.explanation,
                remaining_seconds=exercise.task["duration_minutes"] * 60))
        else:
            raise RoomConflict("This exercise action is not available in its current state.")
        reason = f"{request.reason} (+{request.extra_minutes} minutes)" if action == "extend" else request.reason
        self.event(exercise, action, f"interviewer:{user_id}", reason)
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
            raise RoomConflict("This attempt is no longer active. Refresh to recover your work.")
        if attempt.status == "submitted" and request.submit and request.content == attempt.content and request.explanation == attempt.explanation:
            return self.present(db, exercise, candidate=True)  # Lost receipt: idempotent resubmission.
        if attempt.status != "running":
            raise RoomConflict("The exercise is not running. Your last saved work is preserved.")
        if request.revision != attempt.revision:
            raise RoomConflict("This work changed in another tab. Refresh before saving; keep a copy of your unsaved text.")
        attempt.content, attempt.explanation = request.content, request.explanation
        attempt.revision += 1
        attempt.saved_at = self.now()
        if request.submit:
            self.finish(exercise, attempt, "submitted")
        db.commit()
        return self.present(db, exercise, candidate=True)

    def list_templates(self, db, user_id):
        return [{"id": row.id, "task": row.task} for row in db.scalars(select(WorkSampleTemplate).where(
            WorkSampleTemplate.owner_id == user_id).order_by(WorkSampleTemplate.id.desc()).limit(100))]

    def template(self, db, user_id, task):
        row = WorkSampleTemplate(owner_id=user_id, task=task.model_dump())
        db.add(row)
        db.commit()
        return {"id": row.id, "task": row.task}

    def draft_task(self, db, user_id, interview_id, brief):
        row = self.rooms.owned(db, user_id, interview_id)
        self.rooms.usable(db, row, link=False)
        posting = db.get(JobPosting, row.job_posting_id)
        job = db.get(JobDescription, posting.job_description_id)
        context = {"job_title": job.title, "job_description": job.content[:16000], "knowledge": []}
        try:
            from app.rag.service import KnowledgeBaseService
            from app.rag.embeddings import OllamaEmbeddingProvider
            knowledge = KnowledgeBaseService(OllamaEmbeddingProvider())
            chunks = knowledge.search(db, f"{job.title} {brief}"[:5000], top_k=4, min_score=.25)
            context["knowledge"] = [{"title": c.document_title, "excerpt": c.content[:4000]} for c in chunks]
        except Exception:
            # The approved JD still provides role context. Never invent retrieved sources.
            context["knowledge_unavailable"] = True
            db.rollback()
        db.rollback()  # Never hold a database lock during generation.
        notice = "AI draft only. Review the task, materials and criteria before sharing."
        if context.get("knowledge_unavailable"):
            notice += " Knowledge search was unavailable; only the job description was used."
        return {"task": WorkSampleGraph(self.model).draft(context, brief), "sources": context["knowledge"], "notice": notice}

    def assess(self, db, user_id, interview_id, discussion_segment_ids=()):
        row = self.rooms.owned(db, user_id, interview_id, lock=True)
        exercise = self.exercise(db, row.id)
        if not exercise or utc(exercise.expires_at) <= self.now():
            raise LookupError("Exercise not found or expired")
        self.reconcile(db, row, exercise)
        attempts = self.attempts(db, exercise)
        if not attempts:
            raise RoomConflict("Share and finish an exercise before assessing it.")
        attempt = attempts[-1]
        if attempt.status not in FINISHED:
            raise RoomConflict("Finish the attempt before assessing it.")
        old = db.scalar(select(WorkSampleAssessment).where(WorkSampleAssessment.attempt_id == attempt.id))
        if old:
            if old.status == "failed":
                old.status, old.error = "queued", None
        else:
            from app.models.transcription import TranscriptSegment, TranscriptionSession
            if discussion_segment_ids and not attempt.started_at:
                raise ValueError("An unstarted exercise has no attributable discussion evidence")
            selected = list(db.execute(select(TranscriptSegment, TranscriptionSession.expires_at).join(
                TranscriptionSession, TranscriptionSession.id == TranscriptSegment.session_id).where(
                    TranscriptSegment.id.in_(discussion_segment_ids), TranscriptSegment.interview_id == row.id,
                    TranscriptionSession.interview_id == row.id, TranscriptionSession.expires_at > self.now(),
                    TranscriptSegment.start_at >= (attempt.started_at or self.now()))
                .order_by(TranscriptSegment.start_at, TranscriptSegment.id)))
            if len(selected) != len(discussion_segment_ids):
                raise ValueError("Discussion passages must be unexpired and belong to this interview")
            discussion = [{"id": s.id, "speaker": s.speaker, "text": s.text, "start_offset_ms": s.start_offset_ms,
                "source_hash": digest([s.id, s.text, s.start_offset_ms, s.speaker])} for s, _ in selected]
            if sum(len(s["text"]) for s in discussion) > 16000:
                raise ValueError("Select shorter discussion passages (16,000 characters maximum)")
            if selected:
                exercise.expires_at = min(utc(exercise.expires_at), *(utc(expiry) for _, expiry in selected))
            snapshot = {"task": copy.deepcopy(exercise.task), "task_hash": exercise.task_hash,
                "submission": {"content": attempt.content, "explanation": attempt.explanation},
                "submission_hash": attempt.submission_hash, "prompt_version": PROMPT_VERSION,
                "model": get_settings().gemini_chat_model, "discussion": discussion}
            db.add(WorkSampleAssessment(attempt_id=attempt.id, snapshot=snapshot, result={}, status="queued"))
        db.commit()
        return self.present(db, exercise)

    def review(self, db, user_id, interview_id, request):
        row = self.rooms.owned(db, user_id, interview_id, lock=True)
        exercise = self.exercise(db, row.id)
        if not exercise or utc(exercise.expires_at) <= self.now():
            raise LookupError("Exercise not found or expired")
        attempts = self.attempts(db, exercise)
        assessment = db.get(WorkSampleAssessment, request.assessment_id)
        if not assessment or assessment.attempt_id not in {a.id for a in attempts}:
            raise LookupError("Assessment not found")
        if assessment.status != "draft":
            raise RoomConflict("Only an unapproved assessment draft can be reviewed.")
        approved = validated_evaluation(exercise.task, assessment.snapshot["submission"], request.result,
                                        assessment.snapshot.get("discussion", []))
        approved["discussion_sources"] = assessment.snapshot.get("discussion", [])
        assessment.approved_result, assessment.status = approved, "approved"
        assessment.review_reason, assessment.approved_by, assessment.approved_at = request.reason, user_id, self.now()
        self.event(exercise, "assessment_approved", f"interviewer:{user_id}", request.reason)
        db.commit()
        return self.present(db, exercise)

    def process(self, assessment_id):
        with self.factory() as db:
            if db.execute(update(WorkSampleAssessment).where(WorkSampleAssessment.id == assessment_id,
                WorkSampleAssessment.status == "queued").values(status="processing")).rowcount != 1:
                db.rollback()
                return
            db.commit()
            snapshot = copy.deepcopy(db.get(WorkSampleAssessment, assessment_id).snapshot)
        try:
            result = WorkSampleGraph(self.model).graph.invoke({"snapshot": snapshot})["result"]
            with self.factory() as db:
                db.execute(update(WorkSampleAssessment).where(WorkSampleAssessment.id == assessment_id,
                    WorkSampleAssessment.status == "processing").values(status="draft", result=result, error=None))
                db.commit()
        except Exception:
            with self.factory() as db:
                db.execute(update(WorkSampleAssessment).where(WorkSampleAssessment.id == assessment_id,
                    WorkSampleAssessment.status == "processing").values(status="failed",
                        error="Assessment unavailable. Check the model connection and retry. No score was assigned."))
                db.commit()

    @staticmethod
    def recover(db):
        db.execute(update(WorkSampleAssessment).where(WorkSampleAssessment.status == "processing").values(status="queued"))
        db.commit()

    @staticmethod
    def delete_for_interviews(db, ids):
        exercise_ids = select(WorkSampleExercise.id).where(WorkSampleExercise.interview_id.in_(ids))
        attempt_ids = select(WorkSampleAttempt.id).where(WorkSampleAttempt.exercise_id.in_(exercise_ids))
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
                # Reports contain copies of submissions, so remove derivative reports too.
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
            queued = db.scalar(select(WorkSampleAssessment.id).where(WorkSampleAssessment.status == "queued")
                               .order_by(WorkSampleAssessment.id).limit(1))
        if queued is not None:
            self.process(queued)

    @staticmethod
    def report_sources(db, user_id, application_id):
        result = []
        for exercise in db.scalars(select(WorkSampleExercise).where(WorkSampleExercise.application_id == application_id,
                WorkSampleExercise.owner_id == user_id, WorkSampleExercise.expires_at > now()).order_by(WorkSampleExercise.id)):
            attempts = list(db.scalars(select(WorkSampleAttempt).where(WorkSampleAttempt.exercise_id == exercise.id)
                                      .order_by(WorkSampleAttempt.number)))
            for attempt in attempts:
                if attempt.status not in FINISHED:
                    continue
                assessment = db.scalar(select(WorkSampleAssessment).where(WorkSampleAssessment.attempt_id == attempt.id))
                result.append({"interview_id": exercise.interview_id, "exercise_id": exercise.id, "title": exercise.task["title"],
                    "task": exercise.task, "task_hash": exercise.task_hash, "attempt": attempt.number, "status": attempt.status,
                    "content": attempt.content, "explanation": attempt.explanation, "submission_hash": attempt.submission_hash,
                    "assessment_id": assessment.id if assessment else None,
                    "review_status": assessment.status if assessment else "not_assessed",
                    "assessment": assessment.approved_result if assessment and assessment.status == "approved" else None,
                    "approved_by": assessment.approved_by if assessment else None,
                    "approved_at": utc(assessment.approved_at).isoformat() if assessment and assessment.approved_at else None,
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
