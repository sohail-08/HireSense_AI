"""Durable, versioned analysis jobs using the application's database/session worker pattern."""
import asyncio
import copy
from datetime import datetime, timedelta, timezone
from uuid import uuid4
from sqlalchemy import delete, select, update
from sqlalchemy.orm import selectinload
from app.agents.interview_analysis import InterviewAnalysisGraph, digest, present_result, PROMPT_VERSION, PAIRING_VERSION, RUBRIC_VERSION
from app.config import get_settings
from app.database import SessionLocal
from app.llm.gemini import GeminiStructuredClient
from app.models.interview import InterviewSchedule, InterviewBatch
from app.models.interview_analysis import InterviewAnalysisControl, InterviewAnalysisRun, InterviewAnalysisReview
from app.models.scoring import ScoringRun, ScoringConfiguration
from app.models.knowledge import KnowledgeDocument, KnowledgeSourceType
from app.rag.embeddings import OllamaEmbeddingProvider
from app.rag.service import KnowledgeBaseService
from app.models.transcription import TranscriptionSession, TranscriptSegment
from app.services.interview_rooms import InterviewRooms, RoomConflict
from app.services.interview_content import utc
from app.services.screening_service import ScreeningService
from app.schemas.interview_analysis import StartAnalysis


class ObsoleteRun(Exception):
    pass


def now():
    return datetime.now(timezone.utc)


class InterviewAnalysisService:
    def __init__(self, model=None, session_factory=None, knowledge=None):
        self.factory = session_factory or SessionLocal
        self.model = model
        self.knowledge = knowledge

    @staticmethod
    def knowledge_references(db):
        documents = db.scalars(select(KnowledgeDocument).where(
            KnowledgeDocument.source_type == KnowledgeSourceType.INTERVIEW_QUESTION)
            .options(selectinload(KnowledgeDocument.chunks)).order_by(KnowledgeDocument.id))
        return [{"id": f"knowledge:{d.id}", "title": d.title, "kind": "answer_guide",
                 "content": "\n\n".join(c.content for c in d.chunks), "version": d.content_hash,
                 "source": "knowledge_base", "document_id": d.id, "source_uri": d.source_uri,
                 "chunk_ids": [c.id for c in d.chunks], "question": d.metadata_json.get("question", ""),
                 "requirement_ids": []}
                for d in documents if d.metadata_json.get("answer_guide") and d.chunks]

    def retrieve_guides(self, question):
        knowledge = self.knowledge or KnowledgeBaseService(OllamaEmbeddingProvider())
        with self.factory() as db:
            chunks = knowledge.search(db, question[:5000], top_k=8, min_score=.25,
                                      source_type=KnowledgeSourceType.INTERVIEW_QUESTION)
            return [f"knowledge:{chunk.document_id}" for chunk in chunks]

    @staticmethod
    def latest(db, interview_id):
        return db.scalar(select(InterviewAnalysisRun).where(InterviewAnalysisRun.interview_id == interview_id)
                         .order_by(InterviewAnalysisRun.version.desc()).limit(1))

    @staticmethod
    def control(db, row, user_id):
        control = db.get(InterviewAnalysisControl, row.id)
        if not control:
            control = InterviewAnalysisControl(interview_id=row.id, requested_by=user_id, automatic=False,
                                               references=[], revision=0)
            db.add(control)
            db.flush()
        return control

    @staticmethod
    def requirements(db, row):
        # Prefer the approved ranking configuration used when scheduling this interview.
        batch = db.get(InterviewBatch, row.batch_id)
        ranking = db.get(ScoringRun, batch.ranking_run_id) if batch and batch.ranking_run_id else None
        config = db.get(ScoringConfiguration, ranking.configuration_id) if ranking else None
        if config and config.snapshot.get("requirements"):
            requirements = [{**r, "key": r.get("requirement_id", r.get("key"))} for r in config.snapshot["requirements"]]
            return {"requirements": requirements, "source": "scheduled_approved_scoring_configuration", "configuration_id": config.id}, config.requirement_version
        _, _, profile = ScreeningService._owned_context(db, interviewer_user_id=row.created_by_user_id, job_posting_id=row.job_posting_id)
        snapshot, version = ScreeningService._requirement_snapshot(profile)
        snapshot["source"] = "approved_profile_at_analysis_request"
        return snapshot, version

    def inputs(self, db, row, control):
        sessions = list(db.scalars(select(TranscriptionSession).where(TranscriptionSession.interview_id == row.id,
                                                                     TranscriptionSession.expires_at > now())))
        rows = list(db.scalars(select(TranscriptSegment).where(TranscriptSegment.interview_id == row.id,
            TranscriptSegment.session_id.in_([s.id for s in sessions])).order_by(TranscriptSegment.start_at, TranscriptSegment.sequence, TranscriptSegment.id)))
        segments = []
        for item in rows:
            data = {k: getattr(item, k) for k in ("id", "interview_id", "session_id", "participant_identity", "speaker", "text",
                    "start_offset_ms", "end_offset_ms", "confidence", "sequence")}
            data.update(start_at=utc(item.start_at).isoformat(), end_at=utc(item.end_at).isoformat())
            data["hash"] = digest(data)
            segments.append(data)
        requirements, version = self.requirements(db, row)
        complete = bool(sessions) and all(s.status in {"completed", "failed"} for s in sessions)
        gaps = []
        if not complete: gaps.append("Transcription is still open; the final exchange may be incomplete.")
        if any(s.status == "failed" for s in sessions): gaps.append("A transcription session failed; some speech may be missing.")
        if len(sessions) > 1: gaps.append("Multiple transcription sessions exist; speech between sessions may be missing.")
        if any((s.metrics or {}).get("reconnections", 0) for s in sessions): gaps.append("Recognition reconnected; the transcript may contain gaps.")
        for session in sessions:
            sequences = sorted(s.sequence for s in rows if s.session_id == session.id)
            if sequences and sequences != list(range(1, max(sequences) + 1)):
                gaps.append("Final transcript segment sequence has gaps; some source text is missing.")
                break
        if not segments: gaps.append("No unexpired final transcript is available.")
        hashes = {s["id"]: s["hash"] for s in segments}
        return {"interview_id": row.id, "application_id": row.application_id, "segments": segments,
                "requirements": requirements, "requirement_version": version,
                "references": self.knowledge_references(db) + copy.deepcopy(control.references), "reference_revision": control.revision,
                "complete": complete, "gaps": gaps, "watermark": hashes,
                "expires_at": min((utc(s.expires_at) for s in sessions), default=now()).isoformat(),
                "provider": "gemini", "model": get_settings().gemini_chat_model, "prompt_version": PROMPT_VERSION,
                "pairing_version": PAIRING_VERSION, "rubric_version": RUBRIC_VERSION,
                "configuration": {"provider_timeout_seconds": 45, "model_attempts": 2, "automatic_interval_seconds": 20}}

    @staticmethod
    def input_key(snapshot):
        return digest({k: snapshot[k] for k in ("watermark", "requirements", "requirement_version", "references", "reference_revision",
                    "complete", "gaps", "provider", "model", "prompt_version", "pairing_version", "rubric_version", "configuration")})

    def enqueue(self, db, user_id, interview_id, request, *, override=None, correction_reason=None):
        row = InterviewRooms().owned(db, user_id, interview_id, lock=True)
        control = self.control(db, row, user_id)
        control.automatic, control.checked_at = request.automatic, now()
        previous = self.latest(db, interview_id)
        snapshot = self.inputs(db, row, control)
        if not snapshot["segments"]:
            db.commit()
            raise RoomConflict("There are no saved final transcript segments to analyze yet.")
        base = self.input_key(snapshot)
        if override is None and previous:
            override = previous.snapshot.get("pairing_override")
        # Keep the interviewer's explicit boundary choice on identical inputs.
        finalize = request.finalize_last or bool(previous and previous.snapshot.get("input_key") == base and previous.snapshot.get("finalize_last"))
        key = digest({"input": base, "override": override, "finalize_last": finalize,
                      "request": uuid4().hex if request.reanalyze or correction_reason else None})
        existing = db.scalar(select(InterviewAnalysisRun).where(InterviewAnalysisRun.interview_id == interview_id,
                                                               InterviewAnalysisRun.fingerprint == key))
        if existing:
            db.commit()
            return existing
        old_watermark = previous.snapshot.get("watermark", {}) if previous else {}
        compatible = previous and not request.reanalyze and all(snapshot["watermark"].get(i) == h for i, h in old_watermark.items()) and all(
            snapshot[k] == previous.snapshot.get(k) for k in ("prompt_version", "pairing_version", "model"))
        old_result = previous.result if compatible and previous.status == "completed" else {}
        # A queued/failed run may still carry the last completed incremental state.
        if compatible and not old_result:
            old_result = {"turns": previous.snapshot.get("previous_turns", []), "pairs": previous.snapshot.get("previous_pairs", [])}
        snapshot.update(input_key=base, finalize_last=finalize, reanalyze=request.reanalyze,
                        previous_turns=copy.deepcopy(old_result.get("turns", [])), previous_pairs=copy.deepcopy(old_result.get("pairs", [])),
                        pairing_override=override, correction_reason=correction_reason,
                        past_suggestions=[s["question"] for p in (old_result.get("pairs") or []) for s in p.get("suggestions", [])])
        historical = db.scalars(select(InterviewAnalysisRun).where(InterviewAnalysisRun.interview_id == interview_id,
            InterviewAnalysisRun.status == "completed").order_by(InterviewAnalysisRun.version.desc()))
        snapshot["past_suggestions"] = list(dict.fromkeys(s["question"] for old in historical
            for p in old.result.get("pairs", []) for s in p.get("suggestions", [])))
        # No provider request is performed while holding this row lock.
        db.execute(update(InterviewAnalysisRun).where(InterviewAnalysisRun.interview_id == interview_id,
            InterviewAnalysisRun.status.in_(["queued", "processing"])).values(status="cancelled", stage="superseded"))
        run = InterviewAnalysisRun(interview_id=row.id, application_id=row.application_id, version=(previous.version + 1 if previous else 1),
            fingerprint=key, snapshot=snapshot, requested_by=user_id, status="queued", stage="queued", result={})
        db.add(run)
        db.commit()
        return run

    def read(self, db, user_id, interview_id, run_id=None):
        row = InterviewRooms().owned(db, user_id, interview_id)
        control = db.get(InterviewAnalysisControl, row.id)
        run = db.get(InterviewAnalysisRun, run_id) if run_id else self.latest(db, row.id)
        if run_id and (not run or run.interview_id != row.id): raise LookupError("Analysis not found")
        versions = [{"id": r.id, "version": r.version, "status": r.status, "created_at": r.created_at.isoformat()}
                    for r in db.scalars(select(InterviewAnalysisRun).where(InterviewAnalysisRun.interview_id == row.id)
                        .order_by(InterviewAnalysisRun.version.desc()).limit(100)) if datetime.fromisoformat(r.snapshot["expires_at"]) > now()]
        response = {"run": None, "versions": versions, "automatic": bool(control and control.automatic),
                    "reference_revision": control.revision if control else 0, "references": control.references if control else []}
        if run and datetime.fromisoformat(run.snapshot["expires_at"]) > now():
            current = self.inputs(db, row, control or InterviewAnalysisControl(references=[], revision=0))
            suggestion_ids = {s["id"] for pair in run.result.get("pairs", []) for s in pair.get("suggestions", [])}
            reviews = [{"id": r.id, "kind": r.kind, "target_id": r.target_id, "payload": r.payload, "created_at": r.created_at.isoformat()}
                       for r in db.scalars(select(InterviewAnalysisReview).where(InterviewAnalysisReview.interview_id == row.id).order_by(InterviewAnalysisReview.id))
                       if r.run_id == run.id or (r.kind.startswith("suggestion_") and r.target_id in suggestion_ids)]
            response["run"] = {"id": run.id, "version": run.version, "status": run.status, "stage": run.stage,
                "error": run.error, "created_at": run.created_at.isoformat(), "stale": run.snapshot["input_key"] != self.input_key(current),
                "snapshot": {k: v for k, v in run.snapshot.items() if k not in {"previous_pairs", "previous_turns", "past_suggestions"}},
                "result": present_result(run.result), "reviews": reviews}
        return response

    def references(self, db, user_id, interview_id, request):
        row = InterviewRooms().owned(db, user_id, interview_id, lock=True)
        control = self.control(db, row, user_id)
        if control.revision != request.revision: raise RoomConflict("References changed. Refresh before saving.")
        requirements, _ = self.requirements(db, row)
        ids = {r["key"] for r in requirements["requirements"]}
        if len({r.id for r in request.references}) != len(request.references): raise ValueError("Duplicate reference IDs")
        refs = []
        for item in request.references:
            if not set(item.requirement_ids).issubset(ids): raise ValueError("Unknown requirement")
            ref = item.model_dump()
            ref.update(version=digest(ref), approved_by=user_id, approved_at=now().isoformat())
            refs.append(ref)
        control.references, control.revision = refs, control.revision + 1
        db.execute(update(InterviewAnalysisRun).where(InterviewAnalysisRun.interview_id == interview_id,
            InterviewAnalysisRun.status.in_(["queued", "processing"])).values(status="cancelled", stage="references_changed"))
        db.commit()
        return {"reference_revision": control.revision, "references": refs}

    def correct(self, db, user_id, interview_id, request):
        InterviewRooms().owned(db, user_id, interview_id, lock=True)
        latest = self.latest(db, interview_id)
        if not latest or latest.id != request.run_id or latest.status != "completed": raise RoomConflict("Correct the latest completed analysis version.")
        segments = {s["id"]: s for s in latest.snapshot["segments"]}
        used, ids = set(), set()
        pairs = [p.model_dump() for p in request.pairs]
        for pair in pairs:
            if pair["id"] in ids: raise ValueError("Duplicate pair ID")
            ids.add(pair["id"])
            if pair["unanswered"] and pair["answer_ids"]: raise ValueError("Unanswered exchange cannot have answer segments")
            for field in ("question_ids", "answer_ids", "context_ids"):
                for i in pair[field]:
                    source = segments.get(i)
                    if not source or i in used: raise ValueError("Unknown or reused transcript segment")
                    if field == "question_ids" and source["speaker"] != "INTERVIEWER": raise ValueError("Question speaker mismatch")
                    if field == "answer_ids" and source["speaker"] != "CANDIDATE": raise ValueError("Answer speaker mismatch")
                    used.add(i)
        required = {i for p in latest.result.get("pairs", []) for i in p["question_ids"] + p["answer_ids"] + p["context_ids"]}
        if not required.issubset(used): raise ValueError("Retain all existing segments; move them to context or exclude the exchange")
        db.add(InterviewAnalysisReview(interview_id=interview_id, run_id=latest.id, kind="pairing_correction", target_id="pairs",
            payload={"reason": request.reason, "pairs": pairs}, created_by=user_id))
        control = db.get(InterviewAnalysisControl, interview_id)
        return self.enqueue(db, user_id, interview_id, StartAnalysis(automatic=bool(control and control.automatic)), override=pairs, correction_reason=request.reason)

    def review(self, db, user_id, interview_id, run_id, request):
        InterviewRooms().owned(db, user_id, interview_id, lock=True)
        run = db.get(InterviewAnalysisRun, run_id)
        if not run or run.interview_id != interview_id or run.status != "completed": raise LookupError("Analysis not found")
        if datetime.fromisoformat(run.snapshot["expires_at"]) <= now(): raise LookupError("Analysis expired")
        pair_ids = {p["id"] for p in run.result["pairs"]}
        suggestion_ids = {s["id"] for p in run.result["pairs"] for s in p.get("suggestions", [])}
        if request.target_id not in (pair_ids if request.kind == "assessment_review" else suggestion_ids): raise ValueError("Unknown review target")
        if request.kind == "suggestion_linked":
            sources = list(db.scalars(select(TranscriptSegment).join(TranscriptionSession).where(TranscriptSegment.interview_id == interview_id,
                TranscriptionSession.expires_at > now(), TranscriptSegment.id.in_(request.segment_ids))))
            if not sources or len(sources) != len(set(request.segment_ids)) or any(s.speaker != "INTERVIEWER" for s in sources):
                raise ValueError("Link to this interview's spoken interviewer question")
        db.add(InterviewAnalysisReview(interview_id=interview_id, run_id=run_id, kind=request.kind, target_id=request.target_id,
            payload={"note": request.note, "segment_ids": request.segment_ids}, created_by=user_id))
        db.commit()
        return {"saved": True}

    def process(self, run_id):
        with self.factory() as db:
            claimed = db.execute(update(InterviewAnalysisRun).where(InterviewAnalysisRun.id == run_id,
                InterviewAnalysisRun.status == "queued").values(status="processing", stage="starting"))
            db.commit()
            if claimed.rowcount != 1: return
            run = db.get(InterviewAnalysisRun, run_id)
            snapshot, owner, interview_id = copy.deepcopy(run.snapshot), run.requested_by, run.interview_id
        def checkpoint(stage):
            with self.factory() as db:
                run = db.get(InterviewAnalysisRun, run_id)
                if not run or run.status != "processing" or datetime.fromisoformat(snapshot["expires_at"]) <= now(): raise ObsoleteRun()
                InterviewRooms().owned(db, owner, interview_id)
                run.stage = stage
                db.commit()
        def persist(result):
            with self.factory() as db:
                row = InterviewRooms().owned(db, owner, interview_id, lock=True)
                run = db.get(InterviewAnalysisRun, run_id, populate_existing=True)
                if not run or run.status != "processing": raise ObsoleteRun()
                control = db.get(InterviewAnalysisControl, interview_id)
                current = self.inputs(db, row, control)
                # Appended finals are handled by a following incremental run; changed sources cancel this one.
                if current["references"] != snapshot["references"] or current["requirement_version"] != snapshot["requirement_version"] or any(current["watermark"].get(i) != h for i, h in snapshot["watermark"].items()):
                    run.status, run.stage = "cancelled", "inputs_changed"
                else:
                    run.result, run.status, run.stage, run.completed_at = result, "completed", "completed", now()
                db.commit()
        try:
            InterviewAnalysisGraph(self.model or GeminiStructuredClient(timeout_seconds=45), checkpoint, persist,
                                   retrieve=self.retrieve_guides).graph.invoke(
                {"snapshot": snapshot}, config={"recursion_limit": 15})
        except ObsoleteRun:
            with self.factory() as db:
                db.execute(update(InterviewAnalysisRun).where(InterviewAnalysisRun.id == run_id, InterviewAnalysisRun.status == "processing")
                           .values(status="cancelled", stage="obsolete"))
                db.commit()
        except Exception:
            # Never log exception repr: it may embed transcript text or provider output.
            with self.factory() as db:
                db.execute(update(InterviewAnalysisRun).where(InterviewAnalysisRun.id == run_id, InterviewAnalysisRun.status == "processing")
                    .values(status="failed", stage="failed", error="Analysis could not finish. Review the transcript and retry.", completed_at=now()))
                db.commit()

    def tick(self):
        with self.factory() as db:
            # One model job at a time per backend process. HTTP requests only enqueue.
            pending = db.scalar(select(InterviewAnalysisRun.id).where(InterviewAnalysisRun.status == "queued").order_by(InterviewAnalysisRun.id).limit(1))
            controls = list(db.scalars(select(InterviewAnalysisControl).where(InterviewAnalysisControl.automatic.is_(True),
                                     InterviewAnalysisControl.checked_at < now() - timedelta(seconds=20)).limit(20))) if pending is None else []
            for control in controls:
                latest = self.latest(db, control.interview_id)
                control.checked_at = now()
                db.commit()
                if latest and latest.status in {"queued", "processing", "failed"}: continue
                try:
                    self.enqueue(db, control.requested_by, control.interview_id, StartAnalysis())
                except (LookupError, PermissionError, ValueError):
                    db.rollback()
        if pending is not None: self.process(pending)

    @staticmethod
    def recover(db):
        # Recover durable work after process restart; generation is never triggered by GET/page refresh.
        db.execute(update(InterviewAnalysisRun).where(InterviewAnalysisRun.status == "processing")
                   .values(status="queued", stage="restart_recovery"))
        db.commit()

    @staticmethod
    def delete_for_interviews(db, ids):
        from app.services.assessment_service import AssessmentService
        AssessmentService.delete_sources(db, interview_ids=ids)
        for interview in db.scalars(select(InterviewSchedule).where(InterviewSchedule.id.in_(ids))):
            messages = [m for m in (interview.copilot_messages or []) if m.get("tool_name") != "interview_analysis"]
            if messages != interview.copilot_messages:
                interview.copilot_messages = messages
                interview.copilot_version += 1
        db.execute(delete(InterviewAnalysisReview).where(InterviewAnalysisReview.interview_id.in_(ids)))
        db.execute(delete(InterviewAnalysisRun).where(InterviewAnalysisRun.interview_id.in_(ids)))
        db.execute(delete(InterviewAnalysisControl).where(InterviewAnalysisControl.interview_id.in_(ids)))


async def analysis_worker(stop):
    service = InterviewAnalysisService()
    while not stop.is_set():
        try:
            await asyncio.to_thread(service.tick)
            from app.services.assessment_service import AssessmentService
            await asyncio.to_thread(AssessmentService().tick)
            from app.services.final_ranking_service import FinalRankingService
            await asyncio.to_thread(FinalRankingService().tick)
        except Exception:
            pass  # Safe retry for DB availability; failures never affect media or disclose source text.
        try:
            await asyncio.wait_for(stop.wait(), timeout=2)
        except asyncio.TimeoutError:
            pass
