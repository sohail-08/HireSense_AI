from pathlib import Path


# Resolve the repository-level file, not a .env in the process working directory.
# Docker receives its configuration through explicitly scoped environment variables.
ROOT_ENV_FILE = Path(__file__).resolve().parents[2] / ".env"
