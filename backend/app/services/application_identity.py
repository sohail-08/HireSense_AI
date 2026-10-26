"""Application-owned form profiles and conservative, non-destructive repeat grouping."""
from datetime import datetime, timezone
import re
from uuid import uuid4
from sqlalchemy import select, func
from email_validator import validate_email, EmailNotValidError
from app.config import get_settings
from app.models.candidate import Candidate, CandidateApplication, CVDocument, ApplicationSource
from app.models.interview import InterviewSchedule

FIELDS = {
    "name": ("name", "full name", "candidate name"),
    "email": ("email", "email address", "candidate email"),
    "phone": ("phone", "phone number", "phone numer", "mobile", "mobile number"),
    "linkedin_url": ("linkedin", "linkedin url", "linkedin profile"),
    "portfolio_url": ("portfolio", "portfolio url", "website"),
    "location": ("location", "current location", "city", "country"),
}
SETTINGS_FIELDS = {"linkedin_url": "linkedin", "portfolio_url": "portfolio"}
LIMITS = dict(name=200, email=254, phone=50, linkedin_url=2048, portfolio_url=2048, location=200)


def normal(value):
    return " ".join(str(value or "").strip().casefold().split())


def submitted_profile(record, settings=None):
    settings = settings or get_settings()
    # Match the intake service's supported punctuation and descriptive headers.
    def header(value):
        return re.sub(r"[^a-z0-9]+", " ", str(value or "").lower()).strip()
    values = {header(k): v for k,v in record.items() if not str(k).startswith("_")}
    profile = {}
    for field, aliases in FIELDS.items():
        configured = getattr(settings, "google_forms_" + SETTINGS_FIELDS.get(field, field) + "_column", "")
        keys = [header(configured), *aliases]
        key = next((k for k in keys if k in values), None)
        if key is None:
            key = next((k for k in values if any(len(alias) >= 3 and alias in k for alias in keys)), None)
        value = values.get(key)
        value = str(value).strip()[:LIMITS[field]] if value is not None else None
        if field == "email" and value:
            try: value = validate_email(value, check_deliverability=False).normalized.lower()
            except EmailNotValidError: value = None
        profile[field] = value or None
    return profile


def bind_profile(db, application, profile):
    """Never update a profile that another application or standalone CV shares."""
    if not profile.get("name") and not profile.get("email"):
        return False
    candidate = db.get(Candidate, application.candidate_id) if application.candidate_id else None
    changed = [key for key, value in profile.items() if not candidate or getattr(candidate, key) != value]
    shared = bool(candidate and (
        db.scalar(select(func.count()).select_from(CandidateApplication).where(CandidateApplication.candidate_id == candidate.id)) > 1
        or db.scalar(select(CVDocument.id).where(CVDocument.candidate_id == candidate.id, CVDocument.application_id.is_(None)).limit(1))))
    if not changed and not shared:
        return False
    previous_id = application.candidate_id
    identity_changed = bool(set(changed) & {"name", "email"})
    if not candidate or shared:
        candidate = Candidate(**profile)
        db.add(candidate); db.flush()
        application.candidate_id = candidate.id
        # Avoid a previously-loaded relationship returning the old shared profile.
        application.candidate = candidate
    else:
        for field, value in profile.items(): setattr(candidate, field, value)
    for doc in db.scalars(select(CVDocument).where(CVDocument.application_id == application.id)):
        doc.candidate_id = candidate.id
    record = dict(application.response_data or {})
    record["_identity_repair"] = {"version": "application-profile-v1", "previous_candidate_id": previous_id,
        "changed_fields": changed, "at": datetime.now(timezone.utc).isoformat()}
    application.response_data = record
    if identity_changed:
        # A result obtained against mislabelled identity must not survive repair.
        from app.models.identity import FaceReference
        from app.services.candidate_identity import CandidateIdentityService
        for interview_id in db.scalars(select(InterviewSchedule.id).where(InterviewSchedule.application_id == application.id)):
            CandidateIdentityService.invalidate(db, interview_id)
        ref = db.scalar(select(FaceReference).where(FaceReference.application_id == application.id).with_for_update())
        if ref and ref.consent != "withdrawn":
            ref.photo_cipher = ref.embedding_cipher = None
            ref.status, ref.consent, ref.consented_at = "invalid_photo", "pending", None
            ref.error, ref.generation = "identity_changed", uuid4().hex
    db.flush()
    return True


def canonical_applications(db, applications, *, mark_repeats=False):
    """Keep originals; collapse only exact, same-job form repeats in current cohorts.

    Different names, emails, CV versions or dispositions remain separate.
    Existing interview/biometric activity is never displaced by a fresh duplicate.
    Multiple independently actioned applications remain separately accessible.
    """
    applications = list(applications)
    if not applications: return []
    ids = [a.id for a in applications]
    documents = {}
    for app_id, checksum in db.execute(select(CVDocument.application_id, CVDocument.sha256).where(CVDocument.application_id.in_(ids))):
        documents.setdefault(app_id, set()).add(checksum)
    protected = set(db.scalars(select(InterviewSchedule.application_id).where(InterviewSchedule.application_id.in_(ids))))
    from app.models.identity import FaceReference
    protected.update(db.scalars(select(FaceReference.application_id).where(FaceReference.application_id.in_(ids),
        FaceReference.photo_cipher.is_not(None) | FaceReference.embedding_cipher.is_not(None) | FaceReference.consent.in_(["given", "withdrawn"]))))
    groups = {}
    for app in applications:
        key = ("application", app.id)
        if app.source == ApplicationSource.GOOGLE_FORM and documents.get(app.id):
            profile = submitted_profile(app.response_data or {})
            if profile["email"] and profile["name"]:
                key = (app.job_posting_id, normal(profile["name"]), profile["email"],
                    tuple(sorted(documents[app.id])), app.status)
        groups.setdefault(key, []).append(app)
    keep = set()
    from app.agents.interview_analysis import digest
    for key, group in groups.items():
        key_hash = digest(key)
        actioned = [a.id for a in group if a.id in protected]
        # Preserve a previous grouping if its canonical submission was deleted;
        # retained historical repeats must not silently reappear as new candidates.
        available = [a for a in group if not (
            (a.response_data or {}).get("_duplicate_submission", {}).get("fingerprint") == key_hash
            and (a.response_data or {})["_duplicate_submission"].get("canonical_application_id") not in ids
            and a.id not in protected)]
        if not available: continue
        def recency(app):
            value = app.submitted_at or datetime.min.replace(tzinfo=timezone.utc)
            return (value.replace(tzinfo=timezone.utc) if value.tzinfo is None else value.astimezone(timezone.utc), app.id)
        selected = actioned or [max(available, key=recency).id]
        keep.update(selected)
        if mark_repeats:
            for app in available:
                record = dict(app.response_data or {})
                if app.id not in selected:
                    record["_duplicate_submission"] = {"canonical_application_id": min(selected), "fingerprint": key_hash}
                else:
                    record.pop("_duplicate_submission", None)
                if record != app.response_data: app.response_data = record
    return [a for a in applications if a.id in keep]


def current_application_ids(db, job_id):
    return sorted(a.id for a in canonical_applications(db, db.scalars(select(CandidateApplication)
        .where(CandidateApplication.job_posting_id == job_id).order_by(CandidateApplication.id))))
