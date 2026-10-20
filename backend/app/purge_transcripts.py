"""Explicit maintenance command: python -m app.purge_transcripts --purge-expired.

Removes expired, non-running final text and stream/session metadata, not interviews.
No business data is changed merely by importing this module.
"""
import argparse
from datetime import datetime, timezone
from sqlalchemy import delete, select
from app.database import SessionLocal
from app.models.transcription import TranscriptionSession, TranscriptionStream, TranscriptSegment


def purge(db, now):
    ids = list(db.scalars(select(TranscriptionSession.id).where(TranscriptionSession.expires_at <= now,
        TranscriptionSession.status.not_in(["starting", "active", "stopping"]))))
    if ids:
        from app.services.interview_analysis import InterviewAnalysisService
        interviews = list(db.scalars(select(TranscriptionSession.interview_id).where(TranscriptionSession.id.in_(ids))))
        # Analysis snapshots contain exact source text and must not bypass retention.
        InterviewAnalysisService.delete_for_interviews(db, interviews)
        db.execute(delete(TranscriptSegment).where(TranscriptSegment.session_id.in_(ids)))
        db.execute(delete(TranscriptionStream).where(TranscriptionStream.session_id.in_(ids)))
        db.execute(delete(TranscriptionSession).where(TranscriptionSession.id.in_(ids)))
    db.commit()
    return len(ids)


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--purge-expired", action="store_true", required=True)
    parser.parse_args()
    with SessionLocal() as session:
        print({"expired_sessions_deleted": purge(session, datetime.now(timezone.utc))})
