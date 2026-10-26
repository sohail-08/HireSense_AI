"""Local-only YuNet/SFace inference. No demographic or emotion analysis."""
import hashlib
import io
from functools import lru_cache
from pathlib import Path
from threading import Lock

MODELS = {
    "face_detection_yunet_2023mar.onnx": ("face_detection_yunet", "8f2383e4dd3cfbb4553ea8718107fc0423210dc964f9f4280604804ed2552fa4", 232589),
    "face_recognition_sface_2021dec.onnx": ("face_recognition_sface", "0ba9fbfa01b5270c96627c4ef784da859931e02f04419c829e83484087c34e79", 38696353),
}
MODEL_VERSION = "yunet-2023mar-sface-2021dec:" + MODELS["face_recognition_sface_2021dec.onnx"][1]


class FaceError(ValueError):
    pass


def image_bytes(data):
    from PIL import Image, ImageOps
    if not 0 < len(data) <= 3 * 1024 * 1024:
        raise FaceError("invalid_image")
    try:
        with Image.open(io.BytesIO(data)) as image:
            if image.format not in {"JPEG", "PNG"} or image.width * image.height > 12_000_000 or min(image.size) < 120 or max(image.size) > 6000:
                raise FaceError("invalid_image")
            image.load()
            result = ImageOps.exif_transpose(image).convert("RGB")
            result.thumbnail((960, 960))
            out = io.BytesIO()
            result.save(out, format="JPEG", quality=90)  # Discard EXIF/location metadata.
            return out.getvalue()
    except FaceError:
        raise
    except Exception:
        raise FaceError("invalid_image") from None


def checked_model_paths(directory):
    paths = []
    for name, (_, expected, _) in MODELS.items():
        path = Path(directory).resolve() / name
        if not path.is_file() or hashlib.sha256(path.read_bytes()).hexdigest() != expected:
            raise FaceError("model_unavailable")
        paths.append(str(path))
    return paths


class FaceEngine:
    version = MODEL_VERSION
    def __init__(self, directory):
        try:
            import cv2
            detector, recognizer = checked_model_paths(directory)
            cv2.setNumThreads(1)
            self.detector = cv2.FaceDetectorYN.create(detector, "", (320, 320), .9, .3, 5000)
            self.recognizer = cv2.FaceRecognizerSF.create(recognizer, "")
            self.lock = Lock()
        except FaceError:
            raise
        except Exception:
            raise FaceError("model_unavailable") from None

    def embedding(self, data):
        import cv2
        import numpy as np
        image = cv2.imdecode(np.frombuffer(image_bytes(data), np.uint8), cv2.IMREAD_COLOR)
        with self.lock:
            h, w = image.shape[:2]
            self.detector.setInputSize((w, h))
            faces = self.detector.detect(image)[1]
            if faces is None or len(faces) == 0:
                raise FaceError("no_face")
            if len(faces) != 1:
                raise FaceError("multiple_faces")
            face = faces[0]
            x, y, width, height = face[:4].astype(int)
            if min(width, height) < 70 or x < 0 or y < 0 or x + width > w or y + height > h:
                raise FaceError("poor_image")
            gray = cv2.cvtColor(image[y:y+height, x:x+width], cv2.COLOR_BGR2GRAY)
            if cv2.Laplacian(gray, cv2.CV_64F).var() < 25 or gray.mean() < 35 or gray.mean() > 230:
                raise FaceError("poor_image")
            aligned = self.recognizer.alignCrop(image, face)
            vector = self.recognizer.feature(aligned).reshape(-1).astype(float)
        norm = np.linalg.norm(vector)
        if len(vector) != 128 or not np.isfinite(vector).all() or norm <= 0:
            raise FaceError("model_unavailable")
        return (vector / norm).tolist()


@lru_cache(maxsize=2)
def get_engine(directory):
    return FaceEngine(directory)
