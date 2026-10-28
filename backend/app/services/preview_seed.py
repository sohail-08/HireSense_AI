"""Opt-in, resumable local fixtures. Never invoked by startup or production workers.

Names, CVs, conversations and assessment labels are authored examples, not real
people or provider output. Provenance stays in private metadata, not UI badges.
No biometric consent, camera match, delivery or external publication is invented.
"""
import copy
import hashlib
from datetime import datetime, timedelta, timezone
from uuid import uuid4
from zoneinfo import ZoneInfo
from sqlalchemy import select
from app.agents.interview_analysis import canonical_quote, digest, score_pair
from app.agents.practical_scoring import POLICY, PROMPT_VERSION as PRACTICAL_PROMPT, LIMITATION, validate_evaluation
from app.assessments.sources import resolve_sources
from app.assessments.workflow import ConsolidatedAssessmentGraph, PROMPT_VERSION as REPORT_PROMPT
from app.assessments.final_scoring import FORMULA_VERSION, POLICY as FINAL_POLICY, rank_reports
from app.config import get_settings
from app.models.candidate import Candidate, CandidateApplication, CVDocument, ApplicationSource, ApplicationStatus, CVProcessingStatus
from app.models.job import RequirementProfile, JobDescription, JobPosting, RequirementProfileStatus, JobDescriptionStatus, JobPostingStatus
from app.models.screening import ScreeningRun, ScreeningRunStatus, RequirementMatch, RequirementMatchStatus
from app.models.interview import InterviewBatch, InterviewSchedule
from app.models.interview_analysis import InterviewAnalysisRun
from app.models.transcription import TranscriptionSession, TranscriptionStream, TranscriptSegment
from app.models.work_sample import WorkSampleExercise, WorkSampleAttempt, WorkSampleAssessment
from app.models.assessment import AssessmentRun, AssessmentComparison
from app.models.user import User, UserRole
from app.schemas.assessment import GenerateAssessment
from app.schemas.scoring import ScoringApproval, ScoreRunRequest
from app.schemas.work_sample import Task
from app.services.scoring_service import ScoringService
from app.services.screening_service import ScreeningService
from app.services.interview_analysis import InterviewAnalysisService
from app.services.assessment_service import AssessmentService
from app.services.final_ranking_service import FinalRankingService, source_identity
from app.storage import private_storage_path

SEED = "recruitment-explorer-v1"
PROVENANCE = {"fixture_seed": SEED, "source": "authored fictional examples", "external_actions": False}
ROLES = [
    {"key": "backend", "title": "Backend Engineer", "summary": "Build reliable Python APIs and data services at BJIT.",
     "skills": ["Python API development", "Database transactions", "Automated testing"],
     "degree": "Degree in computing or equivalent experience", "years": 3,
     "questions": [
         ("How would you prevent a payment request from being processed twice?", "Python API development",
          "Use an idempotency key, a unique database constraint and a transaction. Return the saved result for a repeated key; distinguish retryable failures from successful requests."),
         ("How would you test that a failed transaction leaves no partial changes?", "Database transactions",
          "Create an integration test against a real test database, fail after the first write, roll back, and assert both tables remain unchanged. Also test the successful commit path.")],
     "task": {"title": "Order total validation", "instructions": "Write a Python function order_total(items) that sums price * quantity. Reject negative prices and non-positive quantities using ValueError. Return 0 for an empty list.",
          "materials": "Each item is a dictionary with numeric price and integer quantity. No tax or discounts. Example: [{'price': 100, 'quantity': 2}] returns 200.",
          "deliverables": "The function and two short example calls.", "response_type": "code"},
     "people": [
         {"name": "Nadia Rahman", "key": "nadia.rahman", "years": 5, "level": 2, "practical": 100,
          "cv": "Built Python and FastAPI services for order processing. Implemented idempotency keys and PostgreSQL transactions. Wrote integration tests for rollback and payment retries. Five years of backend engineering. BSc in Computer Science.",
          "answers": ["I store a client-provided idempotency key with a unique constraint inside the payment transaction. A retry returns the saved response, and concurrent requests cannot create a second payment. Failed transactions can be retried safely.", "I use a real test database, insert the first row, force the next write to fail, then roll back and query both tables to confirm nothing persisted. I also test that a successful transaction commits both rows."],
          "response": "def order_total(items):\n    total = 0\n    for item in items:\n        price, quantity = item['price'], item['quantity']\n        if price < 0 or quantity <= 0:\n            raise ValueError('Invalid price or quantity')\n        total += price * quantity\n    return total\n\nprint(order_total([{'price': 100, 'quantity': 2}]))  # 200\nprint(order_total([]))  # 0"},
         {"name": "Arif Hasan", "key": "arif.hasan", "years": 3, "level": 1, "practical": 75,
          "cv": "Developed Python REST APIs and SQL queries. Used database transactions in a customer portal. Wrote unit tests with mocked repositories; production rollback tests are not described. Three years of backend development. BSc in Software Engineering.",
          "answers": ["I would keep the request ID in the database and return the old result when I see that ID again. I have not handled two requests with the same ID arriving at exactly the same time.", "I mock the repository and make the second call fail, then assert that rollback was called. I have not checked the resulting table contents in a real database."],
          "response": "def order_total(items):\n    total = 0\n    for item in items:\n        if item['price'] < 0:\n            raise ValueError('Negative price')\n        total += item['price'] * item['quantity']\n    return total\n\nprint(order_total([{'price': 100, 'quantity': 2}]))\nprint(order_total([]))"},
         {"name": "Mehedi Alam", "key": "mehedi.alam", "years": 2, "level": 0, "practical": 40,
          "cv": "Built small Python API endpoints and performed manual SQL checks. Familiar with database transaction terminology. Automated testing was limited to introductory tutorials. Two years of software development. BSc in Computer Science.",
          "answers": ["I would disable the submit button after the first click. I am not sure how to prevent a repeated request from another device or a network retry.", "I would try the failed request manually and look at the API error. I have not written an automated rollback test or checked whether the first write remained."],
          "response": "def order_total(items):\n    return sum(item['price'] for item in items)\n\nprint(order_total([{'price': 100, 'quantity': 2}]))\nprint(order_total([]))"}]},
    {"key": "hr", "title": "HR Executive", "summary": "Support fair, organised recruitment and employee onboarding at BJIT.",
     "skills": ["Structured interviewing", "Recruitment coordination", "Confidential record handling"],
     "degree": "Degree in human resources, business or equivalent experience", "years": 2,
     "questions": [
         ("How would you compare candidates fairly in a structured interview?", "Structured interviewing",
          "Use the same job-related core questions and scoring guide for all candidates. Record specific evidence, score independently before panel discussion, and avoid protected personal traits."),
         ("How would you handle a candidate who asks for another applicant's salary details?", "Confidential record handling",
          "Do not disclose another applicant's confidential data. Explain the confidentiality policy and share only the approved salary range for the role. Restrict access to authorised staff.")],
     "task": {"title": "Interview scheduling email", "instructions": "Draft a candidate email confirming the supplied interview details. Include date, local time, duration, meeting link and a request to confirm availability. Do not include information about other applicants.",
          "materials": "Candidate: Sara. Role: HR Executive. Date: 28 October 2026. Time: 10:00 AM Asia/Dhaka. Duration: 30 minutes. Meeting link: https://meet.example.test/hr-interview.",
          "deliverables": "An email subject and body.", "response_type": "text"},
     "people": [
         {"name": "Samira Ahmed", "key": "samira.ahmed", "years": 4, "level": 2, "practical": 100,
          "cv": "Coordinated recruitment and onboarding for growing teams. Used structured interviewing and evidence-based scorecards. Maintained confidential employee records with role-based access. Four years in HR operations. BBA in Human Resource Management.",
          "answers": ["I use the same core job-related questions and an agreed scoring guide. Each interviewer records examples and scores independently before the panel discussion. I exclude personal traits unrelated to the job.", "I would not disclose another applicant's salary. I explain our confidentiality policy and share the approved salary range for this role instead. Only authorised staff should access applicant records."],
          "response": "Subject: HR Executive interview - 28 October\n\nHello Sara,\nYour HR Executive interview is scheduled for 28 October 2026 at 10:00 AM Asia/Dhaka. Please allow 30 minutes.\nJoin here: https://meet.example.test/hr-interview\nPlease reply to confirm your availability.\nKind regards,\nRecruitment team"},
         {"name": "Rafiq Chowdhury", "key": "rafiq.chowdhury", "years": 2, "level": 1, "practical": 80,
          "cv": "Scheduled interviews and prepared onboarding checklists. Assisted structured interviews using a shared question list; independent scorecards were not documented. Handled applicant records under supervisor guidance. Two years in recruitment coordination. BBA in Management.",
          "answers": ["I give candidates the same main questions and write down their examples. We normally discuss the scores together, so I have not used independent scoring before the discussion.", "I would not share another person's salary. I would ask my manager what salary information I am allowed to provide for this vacancy."],
          "response": "Subject: HR Executive interview\n\nHello Sara,\nYour interview is on 28 October 2026 at 10:00 AM Asia/Dhaka.\nMeeting link: https://meet.example.test/hr-interview\nPlease confirm that you can attend.\nRegards,\nRecruitment team"}]}
]


def cv_pdf(name, role, text):
    """Small, self-contained one-page PDF; no remote fonts, assets or renderer."""
    import io
    import textwrap
    from pypdf import PdfWriter
    from pypdf.generic import DictionaryObject, NameObject, DecodedStreamObject
    writer = PdfWriter(); page = writer.add_blank_page(width=595, height=842)
    font = DictionaryObject({NameObject('/Type'): NameObject('/Font'), NameObject('/Subtype'): NameObject('/Type1'), NameObject('/BaseFont'): NameObject('/Helvetica')})
    bold = DictionaryObject({NameObject('/Type'): NameObject('/Font'), NameObject('/Subtype'): NameObject('/Type1'), NameObject('/BaseFont'): NameObject('/Helvetica-Bold')})
    page[NameObject('/Resources')] = DictionaryObject({NameObject('/Font'): DictionaryObject({NameObject('/F1'): writer._add_object(font), NameObject('/F2'): writer._add_object(bold)})})
    def escaped(value): return value.replace('\\', '\\\\').replace('(', '\\(').replace(')', '\\)')
    commands = ["0.24 0.21 0.57 rg 0 716 595 126 re f", f"BT /F2 25 Tf 1 1 1 rg 46 779 Td ({escaped(name)}) Tj ET", f"BT /F1 13 Tf 1 1 1 rg 46 750 Td ({escaped(role)}) Tj ET", "BT /F2 14 Tf 0.13 0.17 0.27 rg 46 677 Td (Professional profile) Tj ET"]
    for index, line in enumerate(textwrap.wrap(text, 76)):
        commands.append(f"BT /F1 11 Tf 0.22 0.27 0.35 rg 46 {646-index*20} Td ({escaped(line)}) Tj ET")
    stream = DecodedStreamObject(); stream.set_data('\n'.join(commands).encode('ascii'))
    page[NameObject('/Contents')] = writer._add_object(stream)
    out = io.BytesIO(); writer.write(out)
    return out.getvalue()


def add(db, value):
    db.add(value); db.flush(); return value


def seed_recruitment(db, owner_id, *, session_factory, pdf_factory=cv_pdf):
    owner = db.get(User, owner_id)
    if not owner or not owner.is_active or owner.role != UserRole.INTERVIEWER:
        raise ValueError("Select an active interviewer account")
    return _seed(db, owner_id, session_factory, pdf_factory)


def _seed(db, owner_id, factory, pdf_factory):
    actor = db.get(User, owner_id)
    if not actor or not actor.is_active or actor.role != UserRole.INTERVIEWER:
        raise ValueError("Select an active interviewer account")
    now = datetime.now(timezone.utc)
    output = []
    for role in ROLES:
        profile = next((p for p in db.scalars(select(RequirementProfile).where(RequirementProfile.created_by_user_id == owner_id))
            if p.generation_metadata.get("fixture_seed") == SEED and p.generation_metadata.get("role") == role["key"]), None)
        if not profile:
            profile = add(db, RequirementProfile(title=role["title"], summary=role["summary"],
                required_skills=[{"name": s, "weight": 1} for s in role["skills"]], qualifications=[{"name": role["degree"], "weight": 1}],
                min_years_experience=role["years"], preferred_skills=[], selection_criteria=[],
                generation_metadata={**PROVENANCE, "role": role["key"]}, status=RequirementProfileStatus.CONFIRMED, created_by_user_id=owner_id))
        job = db.scalar(select(JobDescription).where(JobDescription.requirement_profile_id == profile.id))
        if not job:
            content = f"# {role['title']}\n\n{role['summary']}\n\n## What you will bring\n" + '\n'.join(f"- {s}" for s in role['skills']) + f"\n- {role['degree']}\n- At least {role['years']} years of relevant experience."
            job = add(db, JobDescription(requirement_profile_id=profile.id, title=role["title"], content=content,
                structured_content={"metadata": PROVENANCE}, status=JobDescriptionStatus.APPROVED, version=1, created_by_user_id=owner_id))
        posting = db.scalar(select(JobPosting).where(JobPosting.job_description_id == job.id))
        if not posting:
            posting = add(db, JobPosting(job_description_id=job.id, platform="manual", status=JobPostingStatus.PUBLISHED,
                heading="BJIT is Hiring!", location="Baridhara, Dhaka", published_at=now-timedelta(days=6),
                reviewed_content=job.content, job_description_version=1))
        # Hash the database-normalised timestamp, not the Python pre-insert value.
        db.commit(); db.refresh(profile)
        snapshot, version = ScreeningService._requirement_snapshot(profile)
        apps = []
        for i, person in enumerate(role["people"]):
            reference = f"{SEED}:{owner_id}:{role['key']}:{person['key']}"
            app = db.scalar(select(CandidateApplication).where(CandidateApplication.job_posting_id == posting.id,
                CandidateApplication.source_reference == reference, CandidateApplication.source == ApplicationSource.IMPORT))
            if not app:
                candidate = add(db, Candidate(name=person["name"], email=person["key"]+"@example.test", location="Dhaka, Bangladesh"))
                app = add(db, CandidateApplication(job_posting_id=posting.id, candidate_id=candidate.id, source=ApplicationSource.IMPORT,
                    source_reference=reference, response_data={"_provenance": PROVENANCE}, status=ApplicationStatus.SHORTLISTED,
                    submitted_at=now-timedelta(days=5, hours=i)))
                key = f"cvs/{uuid4().hex}.pdf"
                payload = pdf_factory(person["name"], role["title"], person["cv"])
                path = private_storage_path(key); path.parent.mkdir(parents=True, exist_ok=True); path.write_bytes(payload)
                blocks = [{"id": "page-1", "locator": "PDF page 1", "text": person["cv"]}]
                doc = add(db, CVDocument(application_id=app.id, candidate_id=candidate.id, original_filename=person["name"].replace(' ', '_')+"_CV.pdf",
                    storage_path=key, mime_type="application/pdf", file_size_bytes=len(payload), sha256=hashlib.sha256(payload).hexdigest(),
                    source=ApplicationSource.IMPORT, status=CVProcessingStatus.PROCESSED, extracted_text=person["cv"],
                    extraction_data={"source_blocks": blocks, "_provenance": PROVENANCE}, processed_at=now-timedelta(days=4)))
                run = add(db, ScreeningRun(application_id=app.id, cv_document_id=doc.id, job_posting_id=posting.id,
                    requirement_profile_id=profile.id, status=ScreeningRunStatus.COMPLETED, cv_sha256=doc.sha256,
                    requirement_snapshot_hash=version, requirement_snapshot=snapshot, processing_metadata=PROVENANCE,
                    model_name="authored-fixture-v1", suitability_summary="Relevant experience is documented; explore the highlighted gaps during the interview.",
                    extracted_profile={"summary": person["cv"], "skills": role["skills"], "calculated_total_experience_years": person["years"],
                        "education": [{"qualification": "BSc in Computer Science" if role["key"] == "backend" else "BBA in Human Resources / Management"}]},
                    completed_at=now-timedelta(days=4)))
                counts = {"met": 0, "partially_met": 0, "unmet": 0}
                strengths, gaps = [], []
                for n, requirement in enumerate(snapshot["requirements"]):
                    status = "met" if person["level"] == 2 or requirement["category"] == "qualification" else "partially_met" if person["level"] == 1 or n == 0 else "unmet"
                    counts[status] += 1
                    (strengths if status == "met" else gaps).append({"requirement_key": requirement["key"],
                        "text": f"{requirement['name']}: " + ("relevant evidence is documented." if status == "met" else "verify the scope of demonstrated experience.")})
                    evidence = [{"block_id": "page-1", "locator": "PDF page 1", "quote": person["cv"], "char_start": 0, "char_end": len(person["cv"])}] if status != "unmet" else []
                    db.add(RequirementMatch(screening_run_id=run.id, requirement_key=requirement["key"], category=requirement["category"],
                        name=requirement["name"], details=requirement.get("details"), weight=requirement["weight"], status=RequirementMatchStatus(status),
                        explanation="The saved CV describes relevant evidence." if status == "met" else "The CV provides limited evidence; verify the scope of experience.",
                        evidence=evidence, evidence_gaps=[] if status == "met" else ["Verify depth through a concrete example."], review_flags=[]))
                run.met_count, run.partially_met_count, run.unmet_count = counts.values()
                run.strengths, run.gaps = strengths, gaps
                run.requirement_coverage = (counts["met"]+.5*counts["partially_met"])/sum(counts.values())*100
            apps.append(app)
        db.commit()
        scoring = ScoringService(); proposal = scoring.proposal(db, user_id=owner_id, job_id=posting.id)
        config = scoring.approve(db, user_id=owner_id, job_id=posting.id, data=ScoringApproval.model_validate({"confirmed": True,
            "requirement_version": version, "category_weights": proposal["category_weights"],
            "requirements": [{k:r[k] for k in ("requirement_id", "category", "classification", "weight")} for r in proposal["requirements"]]}))
        cv_run = scoring.run(db, user_id=owner_id, job_id=posting.id, data=ScoreRunRequest(configuration_id=config["id"]))
        batch = db.scalar(select(InterviewBatch).where(InterviewBatch.created_by_user_id == owner_id, InterviewBatch.idempotency_key == f"{SEED}:{role['key']}"))
        if not batch:
            batch = add(db, InterviewBatch(job_posting_id=posting.id, ranking_run_id=cv_run["id"], kind="invitation", status="completed",
                snapshot={**PROVENANCE, "delivery_policy": "local records only; no email generated"}, confirmation_hash=digest([SEED, owner_id, role['key']]),
                idempotency_key=f"{SEED}:{role['key']}", created_by_user_id=owner_id))
        for i, (person, app) in enumerate(zip(role["people"], apps)):
            interview = db.scalar(select(InterviewSchedule).where(InterviewSchedule.batch_id == batch.id, InterviewSchedule.application_id == app.id))
            if not interview:
                start = (now-timedelta(days=1)).replace(hour=3+i, minute=0, second=0, microsecond=0)
                end = start+timedelta(minutes=30)
                interview = add(db, InterviewSchedule(batch_id=batch.id, job_posting_id=posting.id, application_id=app.id,
                    stage="Interview", start_utc=start, end_utc=end, timezone="Asia/Dhaka", local_start=start.astimezone(ZoneInfo("Asia/Dhaka")).isoformat(),
                    duration_minutes=30, mode="sequential", status="completed", room_status="ended", calendar_uid=uuid4().hex+"@hiresense.local",
                    history=[{"kind": "local_fixture", **PROVENANCE}], interview_started_at=start, interview_ended_at=end, created_by_user_id=owner_id))
                _transcript(db, owner_id, interview, person, role, now)
                _practical(db, owner_id, interview, person, role, now)
        db.commit()
        analysis_service = InterviewAnalysisService(session_factory=factory)
        reports = []
        for person, app in zip(role["people"], apps):
            interview = db.scalar(select(InterviewSchedule).where(InterviewSchedule.batch_id == batch.id, InterviewSchedule.application_id == app.id))
            if not analysis_service.latest(db, interview.id):
                _analysis(db, owner_id, interview, person, role, analysis_service)
            db.commit()
            source = resolve_sources(db, owner_id, app.id, GenerateAssessment())
            source.update(model=get_settings().gemini_chat_model, prompt_version=REPORT_PROMPT)
            fingerprint = digest([source["source_key"], REPORT_PROMPT, source["model"], None])
            report = db.scalar(select(AssessmentRun).where(AssessmentRun.application_id == app.id, AssessmentRun.fingerprint == fingerprint))
            if not report:
                result = ConsolidatedAssessmentGraph().graph.invoke({"snapshot": source})["result"]
                if not result["score_summary"]["ready"]:
                    raise ValueError(f"Preview sources incomplete: {result['score_summary'].get('reason')}")
                last = db.scalar(select(AssessmentRun).where(AssessmentRun.application_id == app.id).order_by(AssessmentRun.version.desc()))
                report = add(db, AssessmentRun(application_id=app.id, job_posting_id=posting.id, version=last.version+1 if last else 1,
                    fingerprint=fingerprint, snapshot=source, result=result, status="completed", stage="completed", completeness=result["completeness"],
                    created_by=owner_id, completed_at=now, expires_at=datetime.fromisoformat(source["expires_at"])))
            db.commit()
            reports.append(AssessmentService(session_factory=factory).read(db, owner_id, report.id))
        _ranking(db, owner_id, posting.id, reports, factory)
        output.append({"title": role["title"], "job_posting_id": posting.id, "applications": [a.id for a in apps],
            "reports": [r["id"] for r in reports]})
    return output


def _transcript(db, owner, interview, person, role, now):
    session = add(db, TranscriptionSession(interview_id=interview.id, provider="local_fixture", model="authored-text-v1", language="en-US",
        status="completed", configuration=PROVENANCE, started_by=owner, started_at=interview.start_utc, ended_at=interview.end_utc,
        expires_at=now+timedelta(days=30), worker_identity="local-fixture", connection_status="completed"))
    streams = {}
    for speaker in ("INTERVIEWER", "CANDIDATE"):
        identity = f"local-{interview.id}-{speaker}"
        streams[speaker] = add(db, TranscriptionStream(id=uuid4().hex, session_id=session.id, speaker=speaker,
            participant_reference=owner if speaker == "INTERVIEWER" else interview.application_id, participant_identity=identity,
            track_sid=identity, start_offset_ms=0))
    texts = []
    for question, answer in zip(role["questions"], person["answers"]): texts.extend([("INTERVIEWER", question[0]), ("CANDIDATE", answer)])
    for index, (speaker, text) in enumerate(texts):
        stream = streams[speaker]; offset = (index+1)*30000
        add(db, TranscriptSegment(id=uuid4().hex, session_id=session.id, interview_id=interview.id, stream_id=stream.id, speaker=speaker,
            participant_reference=stream.participant_reference, participant_identity=stream.participant_identity, track_sid=stream.track_sid,
            provider_request_id="local-fixture", provider_segment_id=str(index), sequence=index+1, text=text,
            start_offset_ms=offset, end_offset_ms=offset+20000, stream_start_offset_ms=offset,
            start_at=interview.start_utc+timedelta(milliseconds=offset), end_at=interview.start_utc+timedelta(milliseconds=offset+20000),
            confidence=None, language="en-US", provider_timing=PROVENANCE))


def _practical(db, owner, interview, person, role, now):
    task = Task.model_validate({**role["task"], "duration_minutes": 12, "tools_policy": "Use supplied materials only. No external AI or assistance."}).model_dump()
    start = interview.start_utc+timedelta(minutes=10)
    exercise = add(db, WorkSampleExercise(interview_id=interview.id, application_id=interview.application_id, owner_id=owner,
        task=task, task_hash=digest(task), grading_policy=POLICY, status="submitted", version=5, approved_at=start,
        events=[{"kind": "local_fixture", **PROVENANCE}], expires_at=now+timedelta(days=30)))
    content = person["response"]
    submission = digest({"task_hash": exercise.task_hash, "attempt": 1, "content": content, "explanation": "", "status": "submitted"})
    attempt = add(db, WorkSampleAttempt(exercise_id=exercise.id, number=1, status="submitted", content=content, explanation="", revision=1,
        remaining_seconds=120, deadline_at=start+timedelta(minutes=12), started_at=start, saved_at=start+timedelta(minutes=10),
        finished_at=start+timedelta(minutes=10), submission_hash=submission))
    snapshot = {"policy": POLICY, "prompt_version": PRACTICAL_PROMPT, "model": "authored-fixture-v1", "exercise_id": exercise.id,
        "task_hash": exercise.task_hash, "submission_hash": submission, "task": task, "content": content, "status": "submitted", "_provenance": PROVENANCE}
    summary = "All requested deliverables are present and consistent with the supplied materials." if person["practical"] == 100 else (
        "The main calculation is present, but quantity validation is missing." if role["key"] == "backend" and person["practical"] == 75 else
        "The function ignores quantity and does not validate invalid inputs." if role["key"] == "backend" else "The email includes the date, time, link and confirmation request, but omits the duration.")
    raw = validate_evaluation(snapshot, {"score": person["practical"], "summary": summary,
        "evidence": [{"line_start": 1, "line_end": len(content.splitlines()), "quote": content}]})
    result = {**raw, "verified": True, "verification_reason": "The saved response supports this correctness rating against the supplied task.", "limitation": LIMITATION}
    add(db, WorkSampleAssessment(attempt_id=attempt.id, status="approved", snapshot=snapshot, result=result,
        approved_result=copy.deepcopy(result), approved_by=owner, approved_at=start+timedelta(minutes=12)))


def _analysis(db, owner, interview, person, role, service):
    control = service.control(db, interview, owner)
    requirements, version = service.requirements(db, interview)
    guides = []
    for n, (question, skill, content) in enumerate(role["questions"]):
        key = next(r["key"] for r in requirements["requirements"] if r["name"] == skill)
        guides.append({"id": f"guide-{interview.id}-{n}", "title": question, "question": question, "kind": "answer_guide",
            "content": content, "version": digest(content), "requirement_ids": [key], "approved_by": owner, "_provenance": PROVENANCE})
    control.references, control.revision = guides, 1
    db.flush()
    snapshot = service.inputs(db, interview, control)
    snapshot.update(input_key=service.input_key(snapshot), finalize_last=True, _provenance=PROVENANCE)
    segments = snapshot["segments"]; sources = {s["id"]:s for s in segments}; pairs, turns = [], []
    for n, guide in enumerate(guides):
        q, a = segments[n*2:n*2+2]
        citation = canonical_quote({"segment_id": a["id"], "quote": a["text"]}, sources)
        labels = ("direct", "supported", "complete", "clear") if person["level"] == 2 else ("direct", "partially_supported", "partial", "clear") if person["level"] == 1 else ("partial", "contradicted", "incomplete", "clear")
        assessment = {}
        # Authored offline example marks, not model output or a production label-to-score rule.
        marks = (100, 100, 100, 100) if person["level"] == 2 else (100, 50, 50, 100) if person["level"] == 1 else (50, 0, 0, 100)
        for dimension, label, mark in zip(("relevance", "accuracy", "completeness", "quality"), labels, marks):
            assessment[dimension] = {"label": label, "score": mark, "justification": "The response covers the expected approach." if person["level"] == 2 else "The response addresses part of the question but leaves key safeguards unestablished.",
                "citations": [citation], "references": [{"reference_id": guide["id"], "version": guide["version"], "kind": "answer_guide", "quote": guide["content"]}] if dimension in {"accuracy", "completeness"} else [],
                "support_status": "supported_by_check", "evidence_gaps": [] if person["level"] == 2 else ["Ask for a concrete example covering the missing steps."]}
        assessment["interpretation"] = {"status": "faithful", "meaning": a["text"], "citations": [citation],
            "notes": [], "support_status": "supported_by_check"}
        pair = {"id": f"pair-{interview.id}-{n}", "question_ids": [q["id"]], "answer_ids": [a["id"]], "context_ids": [], "state": "analyzed", "flags": [],
            "question_requirement_ids": guide["requirement_ids"], "assessment": assessment, "suggestions": [],
            "mappings": [{"requirement_id": guide["requirement_ids"][0], "requirement_version": version, "status": "supporting_evidence" if person["level"] == 2 else "partial_evidence",
                "support_status": "supported_by_check", "citations": [citation], "explanation": "The candidate gave a concrete approach." if person["level"] == 2 else "Further verification is needed for the missing safeguards."}]}
        score_pair(pair); pairs.append(pair)
        turns.extend([{"segment_id": q["id"], "kind": "question", "requirement_ids": guide["requirement_ids"]}, {"segment_id": a["id"], "kind": "answer", "requirement_ids": []}])
    add(db, InterviewAnalysisRun(interview_id=interview.id, application_id=interview.application_id, version=1,
        fingerprint=digest([snapshot["input_key"], SEED]), snapshot=snapshot, result={"pairs": pairs, "turns": turns, "unpaired": [], "coverage": [], "gaps": [], "reconciled": True},
        requested_by=owner, status="completed", stage="completed", completed_at=interview.end_utc))


def _ranking(db, owner, job_id, reports, factory):
    sources = [resolve_sources(db, owner, r["application_id"], GenerateAssessment()) for r in reports]
    readiness = FinalRankingService(session_factory=factory).answer_readiness(db, owner, sources)
    fingerprint = digest([FORMULA_VERSION, FinalRankingService.scoring_policy(), [source_identity(s) for s in sources], readiness])
    if db.scalar(select(AssessmentComparison).where(AssessmentComparison.job_posting_id == job_id, AssessmentComparison.fingerprint == fingerprint)):
        return
    ordered, issue = rank_reports(reports)
    if issue: raise ValueError(issue)
    plans = [{"application_id": r["application_id"], "assessment_id": r["id"], "analysis_requested": True,
        "scoring_run_id": source["cv"]["scoring_run_id"], "interview_ids": [i["id"] for i in source["interviews"]],
        "analysis_ids": [i["analysis"]["id"] for i in source["interviews"]]} for r, source in zip(reports, sources)]
    snapshot = {"kind": "final_ranking", "status": "completed", "stage": "completed", "policy": FINAL_POLICY,
        "analysis_readiness": readiness,
        "scoring_policy": FinalRankingService.scoring_policy(), "basis": "Final candidate ranking", "formula_version": FORMULA_VERSION,
        "plans": plans, "selected_cohort_application_ids": [r["application_id"] for r in reports], "source_interview_ids": [i for p in plans for i in p["interview_ids"]],
        "assessment_ids": [r["id"] for r in ordered], "assessments": ordered, "incompatibilities": [], "interview_incompatibilities": [],
        "combined_ranking_available": True, "cv_order_compatible": True, "cohort_policy": "All candidates for this job.", "_provenance": PROVENANCE}
    add(db, AssessmentComparison(job_posting_id=job_id, fingerprint=fingerprint, assessment_ids=snapshot["assessment_ids"], snapshot=snapshot,
        created_by=owner, expires_at=min(datetime.fromisoformat(s["expires_at"]) for s in sources)))
    db.commit()
