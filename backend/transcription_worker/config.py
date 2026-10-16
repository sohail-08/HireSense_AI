from pydantic import Field, SecretStr
from pydantic_settings import BaseSettings, SettingsConfigDict


class WorkerSettings(BaseSettings):
    # Compose supplies only this worker's variables. Never load all application secrets.
    model_config = SettingsConfigDict(extra="ignore", env_file=None)
    livekit_cloud_url: str
    livekit_cloud_api_key: str
    livekit_cloud_api_secret: SecretStr
    deepgram_api_key: SecretStr = SecretStr("")
    transcription_worker_secret: SecretStr = SecretStr("")
    transcription_backend_url: str = "http://backend:8000"
    transcription_agent_name: str = "hiresense-transcriber"
    transcription_queue_size: int = Field(default=128, ge=4, le=1024)
    transcription_flush_seconds: float = Field(default=4, ge=1, le=10)
    transcription_max_retries: int = Field(default=3, ge=0, le=5)

