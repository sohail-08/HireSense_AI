"""Explicit setup command; runtime inference never downloads model files."""
import hashlib
import os
import urllib.request
from pathlib import Path
from app.identity.face import MODELS, checked_model_paths


def provision(directory):
    root = Path(directory).resolve()
    root.mkdir(parents=True, exist_ok=True)
    for name, (folder, digest, size) in MODELS.items():
        target = root / name
        if target.is_file() and hashlib.sha256(target.read_bytes()).hexdigest() == digest:
            continue
        url = f"https://media.githubusercontent.com/media/opencv/opencv_zoo/main/models/{folder}/{name}"
        temporary = root / (name + ".part")
        try:
            with urllib.request.urlopen(url, timeout=60) as response, temporary.open("wb") as output:
                length = 0
                while chunk := response.read(1024 * 1024):
                    length += len(chunk)
                    if length > size:
                        raise ValueError("Model exceeded its pinned size")
                    output.write(chunk)
            if length != size or hashlib.sha256(temporary.read_bytes()).hexdigest() != digest:
                raise ValueError("Model checksum failed")
            os.replace(temporary, target)
            # Retain upstream licence files beside the separately distributed weights.
            for filename in ("LICENSE",):
                license_url = f"https://raw.githubusercontent.com/opencv/opencv_zoo/main/models/{folder}/{filename}"
                with urllib.request.urlopen(license_url, timeout=30) as response:
                    (root / (folder + ".LICENSE")).write_bytes(response.read(100000))
        finally:
            temporary.unlink(missing_ok=True)
    checked_model_paths(root)
    print("Identity model checksums verified; no candidate data was used.")


if __name__ == "__main__":
    from app.config import get_settings
    provision(get_settings().identity_models_dir)
