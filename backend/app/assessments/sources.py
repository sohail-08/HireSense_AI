import copy
from datetime import datetime, timezone
from sqlalchemy import select, or_
from app.agents.interview_analysis import digest
from app.models.candidate import Candidate, CandidateApplication, CVDocument
from app.models.job import JobPosting, JobDescription, RequirementProfile
from app.models.scoring import CandidateScore, ScoringRun, ScoringConfiguration
from app.models.screening import ScreeningRun, RequirementMatch
from app.models.interview import InterviewSchedule
from app.models.interview_analysis import InterviewAnalysisRun, InterviewAnalysisReview
from app.models.transcription import TranscriptionSession, TranscriptSegment
from app.services.screening_service import ScreeningService
from app.services.interview_content import utc

SELECTION_POLICY = "latest-completed-interview-by-scheduled-start-v1"


def owned_application(db, user_id, application_id, lock=False):
    query = select(CandidateApplication, JobDescription).join(JobPosting,
        JobPosting.id == CandidateApplication.job_posting_id).join(JobDescription,
        JobDescription.id == JobPosting.job_description_id).where(CandidateApplication.id == application_id,
        JobDescription.created_by_user_id == user_id)
    if lock:
        query = query.with_for_update()
    row = db.execute(query).first()
    if not row:
        raise LookupError("Candidate application not found")
    return row


def resolve_sources(db, user_id, application_id, request):
    app, job = owned_application(db, user_id, application_id)
    profile = db.get(RequirementProfile, job.requirement_profile_id)
    profile_snapshot, current_version = ScreeningService._requirement_snapshot(profile)
    candidate = db.get(Candidate, app.candidate_id) if app.candidate_id else None
    score_query = select(CandidateScore, ScoringRun).join(ScoringRun,
        ScoringRun.id == CandidateScore.scoring_run_id).where(CandidateScore.application_id == app.id,
        ScoringRun.job_posting_id == app.job_posting_id, ScoringRun.status == "completed")
    if request.scoring_run_id:
        score_query = score_query.where(ScoringRun.id == request.scoring_run_id)
    else:
        score_query = score_query.where(ScoringRun.requirement_version == current_version)
    scored = db.execute(score_query.order_by(ScoringRun.id.desc()).limit(1)).first()
    if request.scoring_run_id and not scored:
        raise LookupError("Scoring version is not available for this application")
    missing, flags, expires = [], [], []
    cv, config, version = None, None, current_version
    latest_cv = db.scalar(select(CVDocument).where(CVDocument.application_id == app.id)
        .order_by(CVDocument.created_at.desc(), CVDocument.id.desc()).limit(1))
    if scored:
        score, scoring = scored
        configuration = db.get(ScoringConfiguration, scoring.configuration_id)
        if not configuration or configuration.job_posting_id != app.job_posting_id or not configuration.approved_by_user_id:
            raise ValueError("The saved score has no compatible approved configuration")
        config, version = copy.deepcopy(configuration.snapshot), scoring.requirement_version
        if version != current_version: missing.append("Selected CV score uses an older approved requirement version")
        if config.get("requirement_version") != version: raise ValueError("Saved scoring configuration and requirement version do not match")
        screening = db.get(ScreeningRun, score.screening_run_id) if score.screening_run_id else None
        if screening and (screening.application_id != app.id or screening.job_posting_id != app.job_posting_id):
            raise ValueError("Screening source does not belong to this application")
        document = db.get(CVDocument, screening.cv_document_id) if screening and screening.cv_document_id else None
        if document and document.application_id != app.id:
            raise ValueError("CV source does not belong to this application")
        matches = list(db.scalars(select(RequirementMatch).where(RequirementMatch.screening_run_id == screening.id))) if screening else []
        cv = {"scoring_run_id": scoring.id, "score_id": score.id, "configuration_id": configuration.id,
            "requirement_version": version, "formula_version": scoring.formula_version,
            "configuration": config, "final_score": str(score.final_score) if score.final_score is not None else None,
            "categories": {"technical": str(score.technical_score) if score.technical_score is not None else None,
                "experience": str(score.experience_score) if score.experience_score is not None else None,
                "qualification": str(score.qualification_score) if score.qualification_score is not None else None},
            "breakdown": copy.deepcopy(score.breakdown), "written_justification": score.written_justification,
            "original_cv_rank": score.rank, "original_cohort": sorted(a["application_id"] for a in scoring.snapshot.get("applications", [])),
            "document_id": document.id if document else None, "document_sha256": document.sha256 if document else None,
            "source_blocks": copy.deepcopy((document.extraction_data or {}).get("source_blocks", [])) if document else [],
            "screening_run_id": screening.id if screening else None, "screening_status": screening.status.value if screening else "missing",
            "screening_version": screening.prompt_version if screening else None,
            "screening_document_sha256": screening.cv_sha256 if screening else None,
            "screening_requirement_version": screening.requirement_snapshot_hash if screening else None,
            "matches": [{"id": m.id, "requirement_id": m.requirement_key, "status": m.status.value,
                "evidence": copy.deepcopy(m.evidence), "explanation": m.explanation} for m in matches],
            "extraction_warnings": list(document.extraction_warnings or []) if document else []}
        if not screening or screening.status.value != "completed": missing.append("Completed CV screening for the selected score")
        if not document: missing.append("Source CV document for the selected screening version")
        if screening and (screening.requirement_snapshot_hash != version or (document and screening.cv_sha256 != document.sha256)):
            missing.append("Compatible CV screening document and requirement version")
        if latest_cv and document and latest_cv.sha256 != document.sha256:
            missing.append("Screening and scoring for the latest uploaded CV")
        if score.final_score is None: missing.append("Saved numeric CV score")
        cv["compatible"] = bool(screening and screening.status.value == "completed" and document and
            screening.requirement_snapshot_hash == version and screening.cv_sha256 == document.sha256 and
            (not latest_cv or latest_cv.sha256 == document.sha256) and score.final_score is not None)
        if cv["extraction_warnings"]: flags.append("CV extraction has limitations; inspect cited text")
    else:
        missing.append("Saved CV score with an approved configuration for these requirements")
        if not latest_cv: missing.append("CV document")
        screening = db.scalar(select(ScreeningRun).where(ScreeningRun.application_id == app.id,
            ScreeningRun.job_posting_id == app.job_posting_id, ScreeningRun.requirement_snapshot_hash == current_version)
            .order_by(ScreeningRun.id.desc()).limit(1))
        document = db.get(CVDocument, screening.cv_document_id) if screening and screening.cv_document_id else latest_cv
        if document and document.application_id != app.id: raise ValueError("CV source does not belong to this application")
        matches = list(db.scalars(select(RequirementMatch).where(RequirementMatch.screening_run_id == screening.id))) if screening else []
        if not screening or screening.status.value != "completed": missing.append("Completed CV screening")
        if document or screening:
            cv = {"scoring_run_id": None, "score_id": None, "configuration_id": None, "requirement_version": current_version,
                "formula_version": "Not scored", "configuration": {"category_weights": {}}, "final_score": None,
                "categories": dict.fromkeys(("technical", "experience", "qualification")), "breakdown": {"counts": {}},
                "written_justification": "No saved score; screening evidence is shown without inventing a percentage.",
                "original_cv_rank": None, "original_cohort": [], "compatible": False,
                "document_id": document.id if document else None, "document_sha256": document.sha256 if document else None,
                "source_blocks": copy.deepcopy((document.extraction_data or {}).get("source_blocks", [])) if document else [],
                "screening_run_id": screening.id if screening else None, "screening_status": screening.status.value if screening else "missing",
                "screening_version": screening.prompt_version if screening else None,
                "screening_document_sha256": screening.cv_sha256 if screening else None,
                "screening_requirement_version": screening.requirement_snapshot_hash if screening else None,
                "matches": [{"id": m.id, "requirement_id": m.requirement_key, "status": m.status.value,
                    "evidence": copy.deepcopy(m.evidence), "explanation": m.explanation} for m in matches],
                "extraction_warnings": list(document.extraction_warnings or []) if document else []}
            if document and latest_cv and document.sha256 != latest_cv.sha256: missing.append("Screening for the latest uploaded CV")
            if screening and document and screening.cv_sha256 != document.sha256: missing.append("CV document revision used by saved screening")
            if cv["extraction_warnings"]: flags.append("CV extraction has limitations; inspect cited text")
    if profile.status.value != "confirmed": missing.append("Confirmed job requirements")
    requirements = copy.deepcopy(config["requirements"] if config else profile_snapshot["requirements"])
    for r in requirements:
        r["key"] = r.get("requirement_id", r.get("key"))
        r["classification"] = r.get("classification") or ("preferred" if r.get("category") == "preferred_skill" else "required")
        r["requirement_version"] = version
    query = select(InterviewSchedule).where(InterviewSchedule.application_id == app.id,
        InterviewSchedule.job_posting_id == app.job_posting_id, InterviewSchedule.created_by_user_id == user_id)
    if request.analysis_run_ids is not None:
        analyses = list(db.scalars(select(InterviewAnalysisRun).where(InterviewAnalysisRun.id.in_(request.analysis_run_ids))))
        if len(analyses) != len(request.analysis_run_ids) or any(a.application_id != app.id for a in analyses):
            raise LookupError("Analysis versions must belong to the selected application")
        analysis_interviews = sorted({a.interview_id for a in analyses})
        if request.interview_ids is not None and set(request.interview_ids) != set(analysis_interviews):
            raise ValueError("Selected analysis and interview sessions must match")
        if len(analysis_interviews) != len(analyses):
            raise ValueError("Select only one analysis version per interview")
        query = query.where(InterviewSchedule.id.in_(analysis_interviews))
    elif request.interview_ids is not None:
        query = query.where(InterviewSchedule.id.in_(request.interview_ids))
    else:
        query = query.where(or_(InterviewSchedule.status == "completed", InterviewSchedule.room_status == "ended"))
        query = query.order_by(InterviewSchedule.start_utc.desc(), InterviewSchedule.id.desc()).limit(1)
    selected = list(db.scalars(query))
    expected = len(request.interview_ids) if request.interview_ids is not None else len(analysis_interviews) if request.analysis_run_ids is not None else None
    if expected is not None and len(selected) != expected:
        raise LookupError("Interview sessions must belong to the selected application")
    if not selected: missing.append("Completed interview (default policy selects the latest completed interview only)")
    interviews = []
    for interview in sorted(selected, key=lambda i: (utc(i.start_utc), i.id)):
        if interview.status != "completed" and interview.room_status != "ended":
            missing.append(f"Completed interview session #{interview.id}")
        sessions = list(db.scalars(select(TranscriptionSession).where(TranscriptionSession.interview_id == interview.id,
            TranscriptionSession.expires_at > datetime.now(timezone.utc))))
        segments = list(db.scalars(select(TranscriptSegment).where(TranscriptSegment.interview_id == interview.id,
            TranscriptSegment.session_id.in_([s.id for s in sessions])).order_by(TranscriptSegment.start_at, TranscriptSegment.sequence)))
        finalized = bool(sessions) and all(s.status in {"completed", "failed"} for s in sessions)
        if not finalized: missing.append(f"Finalized transcript for interview #{interview.id}")
        if not segments: missing.append(f"Saved final transcript text for interview #{interview.id}")
        if any(s.status == "failed" for s in sessions): flags.append(f"Interview #{interview.id}: transcription failed or may contain gaps")
        expires.extend(utc(s.expires_at) for s in sessions)
        analysis_query = select(InterviewAnalysisRun).where(InterviewAnalysisRun.interview_id == interview.id,
            InterviewAnalysisRun.application_id == app.id)
        if request.analysis_run_ids is not None:
            analysis_query = analysis_query.where(InterviewAnalysisRun.id.in_(request.analysis_run_ids))
        analysis = db.scalar(analysis_query.order_by(InterviewAnalysisRun.version.desc()).limit(1))
        if not analysis or analysis.status != "completed": missing.append(f"Completed answer analysis for interview #{interview.id}")
        valid_analysis = bool(analysis and analysis.status == "completed" and datetime.fromisoformat(analysis.snapshot["expires_at"]) > datetime.now(timezone.utc))
        if analysis and not valid_analysis: missing.append(f"Available, unexpired analysis for interview #{interview.id}")
        if valid_analysis and analysis.snapshot.get("requirement_version") != version:
            missing.append(f"Interview #{interview.id} analysis against requirement version {version}")
        sources = {}
        for s in segments:
            data = {k: getattr(s, k) for k in ("id", "interview_id", "session_id", "participant_identity", "speaker", "text", "start_offset_ms", "end_offset_ms", "confidence", "sequence")}
            data.update(start_at=utc(s.start_at).isoformat(), end_at=utc(s.end_at).isoformat())
            data["hash"] = digest(data)
            sources[s.id] = data
        if valid_analysis and analysis.snapshot.get("watermark") != {i: s["hash"] for i, s in sources.items()}:
            missing.append(f"Analysis of the latest finalized transcript for interview #{interview.id}")
        if valid_analysis and not analysis.result.get("reconciled"):
            missing.append(f"Final reconciled answer analysis for interview #{interview.id}")
        reviews = list(db.scalars(select(InterviewAnalysisReview).where(InterviewAnalysisReview.interview_id == interview.id)))
        interviews.append({"id": interview.id, "date": utc(interview.start_utc).isoformat(), "status": interview.status,
            "finalized": finalized, "segments": sources,
            "analysis": {"id": analysis.id, "version": analysis.version, "status": analysis.status,
                "requirement_version": analysis.snapshot.get("requirement_version"), "rubric_version": analysis.snapshot.get("rubric_version"),
                "snapshot": copy.deepcopy(analysis.snapshot), "result": copy.deepcopy(analysis.result)} if valid_analysis else None,
            "reviews": [{"id": r.id, "run_id": r.run_id, "kind": r.kind, "target_id": r.target_id,
                "payload": copy.deepcopy(r.payload), "created_by": r.created_by, "created_at": utc(r.created_at).isoformat()}
                for r in reviews if analysis and r.run_id == analysis.id]})
    from app.services.work_sample import WorkSampleService
    practical = WorkSampleService.report_sources(db, user_id, app.id)
    expires.extend(datetime.fromisoformat(p["expires_at"]) for p in practical)
    snapshot = {"identification": {"application_id": app.id, "job_posting_id": app.job_posting_id,
        "job_title": job.title, "candidate_name": candidate.name if candidate and candidate.name else f"Application #{app.id}",
        "requirement_version": version}, "requirements": requirements, "cv": cv, "interviews": interviews,
        "missing": sorted(set(missing)), "flags": sorted(set(flags)), "selection_policy": SELECTION_POLICY,
        "selection": request.model_dump(exclude={"new_version"}),
        "expires_at": min(expires).isoformat() if expires else None,
        "current_requirement_version": current_version, "current_cv_sha256": latest_cv.sha256 if latest_cv else None,
        "practical_assessments": practical}
    if (app.response_data or {}).get("_identity_repair"):
        # A repaired display identity requires a fresh report, not reuse of a
        # report naming another submission. Unaffected report keys stay unchanged.
        snapshot["identity_revision"] = digest([getattr(candidate, key, None) for key in
            ("name", "email", "phone", "linkedin_url", "portfolio_url", "location")])
    # Stable source identity, not unrelated job/application counters or timestamps.
    snapshot["source_key"] = digest({k: v for k, v in snapshot.items() if k not in {"identification", "expires_at"}})
    return snapshot
