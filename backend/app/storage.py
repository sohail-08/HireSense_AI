from pathlib import Path

from app.config import get_settings


def storage_root() -> Path:
    root = Path(get_settings().storage_root).expanduser()
    root.mkdir(parents=True, exist_ok=True)

    try:
        root.chmod(0o700)
    except OSError:
        # Windows does not expose POSIX permissions in the same way.
        pass

    return root.resolve()


def ensure_storage_root() -> Path:
    return storage_root()


def ensure_cv_storage_root() -> Path:
    directory = private_storage_path("cvs")
    directory.mkdir(parents=True, exist_ok=True)
    return directory


def private_storage_path(relative_path: str) -> Path:
    root = storage_root()
    candidate = (root / relative_path).resolve()

    if candidate != root and root not in candidate.parents:
        raise ValueError(
            "Storage path must remain inside the private storage root"
        )

    return candidate
