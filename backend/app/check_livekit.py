"""Sanitized media status and optional read-only authenticated API check."""
import argparse
import json

from app.config import get_settings
from app.integrations.livekit_media import LiveKitMedia, MediaUnavailable
from app.services.interview_rooms import InterviewRooms


def media_status(check_api=False, settings=None):
    settings = settings or get_settings()
    result = {"mode": "cloud", "configured": False,
              "api_reachable": False, "notice": None, "remote_media_verified": False}
    try:
        media = LiveKitMedia(settings)
        media.configured()
        result["configured"] = True
        result["notice"] = InterviewRooms(settings).media_notice()
        if check_api:
            result["api_reachable"] = bool(media.check_connection())
    except MediaUnavailable as exc:
        # All adapter errors are static, sanitized messages. Never return
        # credentials, connection JWTs, provider bodies or private room names.
        result["notice"] = str(exc)
    return result


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--check-api", action="store_true")
    args = parser.parse_args()
    print(json.dumps(media_status(check_api=args.check_api)))
