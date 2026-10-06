import json
from datetime import date, timedelta

import httpx
import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import Session, sessionmaker
from sqlalchemy.pool import StaticPool

from app.database import Base, get_db
from app.agents.job_posting import (
    JobPostingAssistantGraph,
    PostingCommandExtraction,
)
from app.integrations.discord import (
    DiscordConfigurationError,
    DiscordDeliveryUncertainError,
    DiscordPublishError,
    DiscordPublishResult,
    DiscordWebhookPublisher,
)
from app.models import (
    JobDescription,
    JobDescriptionStatus,
    JobPostingStatus,
    RequirementProfile,
    RequirementProfileStatus,
    User,
    UserRole,
)
from app.routes import job_postings as job_posting_routes
from app.schemas.job_posting import DiscordPostPreviewRequest
from app.security import create_access_token
from app.services.job_posting_service import (
    DiscordJobPostComposer,
    DiscordJobPostingService,
    DiscordPostOptions,
    PublicationConflictError,
    StaleJobDescriptionError,
)
from app.services.job_posting_assistant_service import JobPostingAssistantService


class StubPublisher:
    def __init__(self, outcome):
        self.outcome = outcome
        self.calls = []

    def publish(self, payload):  # noqa: ANN001
        self.calls.append(payload)
        if isinstance(self.outcome, Exception):
            raise self.outcome
        return self.outcome


class StubPostingCommandModel:
    def __init__(self, outcomes):
        self.outcomes = list(outcomes)

    def extract(self, **_kwargs):
        return self.outcomes.pop(0)


def _database():
    engine = create_engine(
        "sqlite://",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    Base.metadata.create_all(engine)
    return engine, sessionmaker(bind=engine, expire_on_commit=False)


def _records(db: Session):
    interviewer = User(
        name="Interviewer",
        email="discord-interviewer@example.com",
        password_hash="hashed-password",
        role=UserRole.INTERVIEWER,
    )
    candidate = User(
        name="Candidate",
        email="discord-candidate@example.com",
        password_hash="hashed-password",
        role=UserRole.CANDIDATE,
    )
    db.add_all([interviewer, candidate])
    db.flush()
    profile = RequirementProfile(
        title="Backend Engineer",
        required_skills=[{"name": "Python"}],
        preferred_skills=[],
        qualifications=[{"name": "Relevant experience"}],
        selection_criteria=[{"name": "Technical interview"}],
        min_years_experience=3,
        status=RequirementProfileStatus.CONFIRMED,
        created_by_user_id=interviewer.id,
    )
    db.add(profile)
    db.flush()
    job = JobDescription(
        requirement_profile_id=profile.id,
        title="Backend Engineer",
        content=(
            "Build reliable APIs.\n\n"
            "## Responsibilities\n- Design services\n- Write tests"
        ),
        structured_content={},
        source_references=[],
        version=2,
        status=JobDescriptionStatus.APPROVED,
        created_by_user_id=interviewer.id,
    )
    db.add(job)
    db.commit()
    return interviewer, candidate, job


def _preview_request(job_id: int, **overrides):
    return DiscordPostPreviewRequest(
        job_description_id=job_id,
        heading="BJIT is Hiring!",
        application_url="https://example.com/apply",
        contact_email="jobs@example.com",
        location="Dhaka",
        additional_instructions="Apply before the deadline.",
        **overrides,
    )


def test_composer_preserves_description_and_orders_header_title_footer():
    description = "Paragraph one.\n\n- First item\n- Second item"
    composed = DiscordJobPostComposer().compose(
        job_title="Backend Engineer",
        job_description=description,
        options=DiscordPostOptions(
            heading="BJIT is Hiring!",
            application_url="https://example.com/apply",
            contact_email="jobs@example.com",
        ),
    )

    assert composed.payload["content"] == "BJIT is Hiring!"
    assert composed.payload["embeds"][0]["title"] == "Backend Engineer"
    assert composed.payload["embeds"][0]["description"] == description
    assert composed.payload["allowed_mentions"] == {"parse": []}
    assert composed.reviewed_content.index("BJIT is Hiring!") == 0
    assert composed.reviewed_content.index("Backend Engineer") < composed.reviewed_content.index(description)
    assert composed.reviewed_content.endswith("Contact email: jobs@example.com")


def test_composer_omits_empty_optional_fields_and_enforces_limits():
    composer = DiscordJobPostComposer()
    composed = composer.compose(
        job_title="Backend Engineer",
        job_description="Short description",
        options=DiscordPostOptions(heading="Hiring"),
    )

    assert "fields" not in composed.payload["embeds"][0]
    assert "example.com" not in composed.reviewed_content

    with pytest.raises(ValueError, match="4096-character"):
        composer.compose(
            job_title="Backend Engineer",
            job_description="x" * 4097,
            options=DiscordPostOptions(heading="Hiring"),
        )

    with pytest.raises(ValueError, match="1024-character"):
        composer.compose(
            job_title="Backend Engineer",
            job_description="Short description",
            options=DiscordPostOptions(
                heading="Hiring",
                additional_instructions="x" * 1025,
            ),
        )


def test_posting_assistant_graph_collects_only_link_and_deadline():
    deadline = date.today() + timedelta(days=14)
    graph = JobPostingAssistantGraph(
        StubPostingCommandModel(
            [
                PostingCommandExtraction(
                    action="provide_details",
                    application_url="https://forms.example.com/apply",
                    application_deadline=deadline,
                )
            ]
        )
    )

    state = graph.invoke(message="Use this application link and deadline")

    assert state["application_url"] == "https://forms.example.com/apply"
    assert state["application_deadline"] == deadline.isoformat()
    assert state["missing_fields"] == []


def test_posting_assistant_asks_then_previews_and_publishes_after_approval():
    engine, sessions = _database()
    deadline = date.today() + timedelta(days=14)
    publisher = StubPublisher(DiscordPublishResult("333", "222", "111"))
    command_model = StubPostingCommandModel(
        [
            PostingCommandExtraction(action="start"),
            PostingCommandExtraction(
                action="provide_details",
                application_url="https://forms.example.com/apply",
                application_deadline=deadline,
            ),
            PostingCommandExtraction(action="approve"),
        ]
    )
    service = JobPostingAssistantService(
        command_model,
        DiscordJobPostingService(publisher=publisher),
    )

    with sessions() as db:
        interviewer, _, job = _records(db)
        requested = service.chat(
            db,
            job_description_id=job.id,
            interviewer_user_id=interviewer.id,
            message="Post this job",
        )
        assert requested["status"] == "awaiting_details"
        assert requested["missing_fields"] == [
            "application_url",
            "application_deadline",
        ]

        prepared = service.chat(
            db,
            job_description_id=job.id,
            interviewer_user_id=interviewer.id,
            message=(
                "Use https://forms.example.com/apply and "
                f"{deadline.isoformat()}"
            ),
        )
        posting = prepared["posting"]
        assert prepared["status"] == "awaiting_approval"
        assert posting.status is JobPostingStatus.DRAFT
        assert posting.application_url == "https://forms.example.com/apply"
        assert posting.application_deadline == deadline
        assert publisher.calls == []

        published = service.chat(
            db,
            job_description_id=job.id,
            interviewer_user_id=interviewer.id,
            posting_id=posting.id,
            message="approve",
        )
        assert published["status"] == "published"
        assert published["posting"].status is JobPostingStatus.PUBLISHED
        assert len(publisher.calls) == 1
    engine.dispose()

def test_confirmed_publication_is_saved_with_discord_link():
    engine, sessions = _database()
    publisher = StubPublisher(
        DiscordPublishResult(
            message_id="333",
            channel_id="222",
            guild_id="111",
        )
    )
    service = DiscordJobPostingService(publisher=publisher)
    with sessions() as db:
        interviewer, _, job = _records(db)
        preview = service.preview(
            db,
            data=_preview_request(job.id),
            interviewer_user_id=interviewer.id,
        )
        published = service.publish(
            db,
            posting_id=preview.id,
            interviewer_user_id=interviewer.id,
        )

        assert published.status is JobPostingStatus.PUBLISHED
        assert published.external_post_id == "333"
        assert published.external_channel_id == "222"
        assert published.external_server_id == "111"
        assert published.external_url == "https://discord.com/channels/111/222/333"
        assert published.published_at is not None
        assert len(publisher.calls) == 1
    engine.dispose()


def test_duplicate_or_concurrent_publish_attempt_is_blocked():
    engine, sessions = _database()
    publisher = StubPublisher(
        DiscordPublishResult("333", "222", "111")
    )
    service = DiscordJobPostingService(publisher=publisher)
    with sessions() as db:
        interviewer, _, job = _records(db)
        preview = service.preview(
            db,
            data=_preview_request(job.id),
            interviewer_user_id=interviewer.id,
        )
        service.publish(
            db,
            posting_id=preview.id,
            interviewer_user_id=interviewer.id,
        )

        with pytest.raises(PublicationConflictError):
            service.publish(
                db,
                posting_id=preview.id,
                interviewer_user_id=interviewer.id,
            )

        assert len(publisher.calls) == 1
    engine.dispose()


def test_stale_job_description_is_not_published():
    engine, sessions = _database()
    publisher = StubPublisher(
        DiscordPublishResult("333", "222", "111")
    )
    service = DiscordJobPostingService(publisher=publisher)
    with sessions() as db:
        interviewer, _, job = _records(db)
        preview = service.preview(
            db,
            data=_preview_request(job.id),
            interviewer_user_id=interviewer.id,
        )
        job.content = "Changed after preview"
        db.commit()

        with pytest.raises(StaleJobDescriptionError):
            service.publish(
                db,
                posting_id=preview.id,
                interviewer_user_id=interviewer.id,
            )

        assert publisher.calls == []
    engine.dispose()


@pytest.mark.parametrize(
    ("error", "expected_status"),
    [
        (
            DiscordConfigurationError(
                "discord_webhook_not_configured",
                "Discord publishing is not configured.",
            ),
            JobPostingStatus.FAILED,
        ),
        (
            DiscordPublishError(
                "discord_webhook_invalid",
                "Discord rejected the webhook.",
            ),
            JobPostingStatus.FAILED,
        ),
        (
            DiscordDeliveryUncertainError(
                "discord_delivery_uncertain",
                "Delivery could not be confirmed.",
            ),
            JobPostingStatus.UNCERTAIN,
        ),
    ],
)
def test_publication_failures_are_persisted(error, expected_status):
    engine, sessions = _database()
    service = DiscordJobPostingService(publisher=StubPublisher(error))
    with sessions() as db:
        interviewer, _, job = _records(db)
        preview = service.preview(
            db,
            data=_preview_request(job.id),
            interviewer_user_id=interviewer.id,
        )

        with pytest.raises(type(error)):
            service.publish(
                db,
                posting_id=preview.id,
                interviewer_user_id=interviewer.id,
            )

        db.expire_all()
        saved = db.get(type(preview), preview.id)
        assert saved.status is expected_status
        assert saved.error_code == error.code
    engine.dispose()


def test_publisher_uses_wait_confirmation_and_bounded_rate_limit_retry():
    requests = []
    sleeps = []

    def handler(request: httpx.Request):
        requests.append(request)
        if len(requests) == 1:
            return httpx.Response(429, json={"retry_after": 0.25})
        return httpx.Response(
            200,
            json={"id": "333", "channel_id": "222", "guild_id": "111"},
        )

    client = httpx.Client(transport=httpx.MockTransport(handler))
    publisher = DiscordWebhookPublisher(
        webhook_url="https://discord.com/api/webhooks/123/token",
        client=client,
        max_rate_limit_wait_seconds=1,
        sleeper=sleeps.append,
    )
    payload = {"content": "Hiring", "allowed_mentions": {"parse": []}}

    result = publisher.publish(payload)

    assert result.message_id == "333"
    assert len(requests) == 2
    assert requests[0].url.params["wait"] == "true"
    assert json.loads(requests[0].content) == payload
    assert sleeps == [0.25]
    client.close()


def test_publisher_handles_deleted_webhook_and_uncertain_timeout():
    invalid_client = httpx.Client(
        transport=httpx.MockTransport(
            lambda _request: httpx.Response(404, json={"message": "Unknown Webhook"})
        )
    )
    invalid_publisher = DiscordWebhookPublisher(
        webhook_url="https://discord.com/api/webhooks/123/secret-token",
        client=invalid_client,
    )
    with pytest.raises(DiscordPublishError) as invalid_error:
        invalid_publisher.publish({"content": "Hiring"})
    assert invalid_error.value.code == "discord_webhook_invalid"
    assert "secret-token" not in invalid_error.value.safe_message
    invalid_client.close()

    def timeout(request: httpx.Request):
        raise httpx.ReadTimeout("timed out", request=request)

    timeout_client = httpx.Client(transport=httpx.MockTransport(timeout))
    uncertain_publisher = DiscordWebhookPublisher(
        webhook_url="https://discord.com/api/webhooks/123/secret-token",
        client=timeout_client,
    )
    with pytest.raises(DiscordDeliveryUncertainError):
        uncertain_publisher.publish({"content": "Hiring"})
    timeout_client.close()


def test_publisher_reports_missing_configuration_without_sending():
    client = httpx.Client(
        transport=httpx.MockTransport(
            lambda _request: pytest.fail("No Discord request should be sent")
        )
    )
    publisher = DiscordWebhookPublisher(webhook_url=None, client=client)
    publisher.webhook_url = None

    with pytest.raises(DiscordConfigurationError) as error:
        publisher.publish({"content": "Hiring"})

    assert error.value.code == "discord_webhook_not_configured"
    assert "DISCORD_WEBHOOK_URL" in error.value.safe_message
    client.close()


def test_job_posting_routes_require_interviewer_and_return_saved_status(monkeypatch):
    engine, sessions = _database()
    publisher = StubPublisher(
        DiscordPublishResult("333", "222", "111")
    )
    service = DiscordJobPostingService(publisher=publisher)
    with sessions() as db:
        interviewer, candidate, job = _records(db)
        interviewer_id = interviewer.id
        candidate_id = candidate.id
        job_id = job.id

    def test_db():
        with sessions() as db:
            yield db

    app = FastAPI()
    app.include_router(job_posting_routes.router)
    app.dependency_overrides[get_db] = test_db
    monkeypatch.setattr(job_posting_routes, "_service", lambda: service)

    with TestClient(app) as api:
        candidate_headers = {
            "Authorization": f"Bearer {create_access_token(candidate_id)}"
        }
        assert api.get(
            "/api/job-postings/discord/defaults",
            headers=candidate_headers,
        ).status_code == 403

        interviewer_headers = {
            "Authorization": f"Bearer {create_access_token(interviewer_id)}"
        }
        preview_response = api.post(
            "/api/job-postings/discord/preview",
            headers=interviewer_headers,
            json={
                "job_description_id": job_id,
                "heading": "BJIT is Hiring!",
            },
        )
        assert preview_response.status_code == 201
        posting_id = preview_response.json()["id"]

        rejected_confirmation = api.post(
            f"/api/job-postings/{posting_id}/publish",
            headers=interviewer_headers,
            json={"confirmed": False},
        )
        assert rejected_confirmation.status_code == 422

        published_response = api.post(
            f"/api/job-postings/{posting_id}/publish",
            headers=interviewer_headers,
            json={"confirmed": True},
        )
        assert published_response.status_code == 200
        assert published_response.json()["status"] == "published"

        saved_response = api.get(
            f"/api/job-postings/discord?job_description_id={job_id}",
            headers=interviewer_headers,
        )
        assert saved_response.status_code == 200
        assert saved_response.json()[0]["status"] == "published"
    engine.dispose()
