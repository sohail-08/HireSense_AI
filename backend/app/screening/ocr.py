"""Bounded, local OCR. Confidence is a quality gate, never a candidate score."""
import csv
import io
import math
import os
import shutil
import subprocess
import tempfile
import time
from pathlib import Path

from PIL import Image

OCR_VERSION = "local-pdf-ocr-v1"


class OCRReadError(ValueError):
    pass


def ocr_page_notice(page_number):
    return f"PDF page {page_number} was read with OCR. Verify important details against the original scan."


def blocking_extraction_warnings(document):
    """Only a verified successful OCR notice is advisory, not a document failure.

    Unknown/legacy warnings remain blocking. Do not rely on wording alone: the
    persisted extraction trace must show that the page passed its quality gate.
    """
    warnings = document.extraction_warnings or []
    if not warnings:
        return []
    advisory = set()
    data = document.extraction_data
    parser = data.get("parser") if isinstance(data, dict) else None
    if isinstance(parser, dict) and parser.get("parser") == "pypdf+tesseract":
        ocr = parser.get("ocr")
        pages = ocr.get("pages") if isinstance(ocr, dict) else None
        for page in pages if isinstance(pages, list) else []:
            try:
                policy = page["identity"]["policy"]
                mean, uncertain = float(page["mean_confidence"]), float(page["uncertain_character_ratio"])
                minimum, maximum = float(policy["min_confidence"]), float(policy["max_uncertain_ratio"])
                number = page["page"]
                if (isinstance(number, int) and not isinstance(number, bool) and number > 0 and not page.get("blank")
                        and all(math.isfinite(v) for v in (mean, uncertain, minimum, maximum))
                        and 50 <= minimum <= mean <= 100 and 0 <= uncertain <= maximum <= 0.5
                        and page["word_count"] >= max(5, policy["min_words"])):
                    advisory.add(ocr_page_notice(number))
            except (KeyError, TypeError, ValueError):
                continue
    return [warning for warning in warnings if warning not in advisory]


class LocalCVOCR:
    def __init__(self, settings):
        self.settings = settings
        self._identity = None

    def policy(self):
        return {"version": OCR_VERSION, "language": self.settings.cv_ocr_language,
            "min_confidence": self.settings.cv_ocr_min_confidence,
            "max_uncertain_ratio": self.settings.cv_ocr_max_uncertain_ratio,
            "max_image_side": self.settings.cv_ocr_max_image_side,
            "page_segmentation": 3, "min_words": 5, "min_characters": 40}

    def identity(self):
        if self._identity is not None:
            return self._identity
        if not self.settings.cv_ocr_enabled:
            raise OCRReadError("CV OCR is disabled. Enable it or upload a readable text-based PDF/DOCX; no candidate score was assigned.")
        if not shutil.which("tesseract") or not shutil.which("pdftoppm"):
            raise OCRReadError("CV OCR is unavailable. Install Tesseract, its language data and Poppler, then retry; no candidate score was assigned.")
        try:
            def info(args):
                result = subprocess.run(args, stdin=subprocess.DEVNULL, stdout=subprocess.PIPE,
                    stderr=subprocess.STDOUT, timeout=5, check=True, encoding="utf-8", errors="replace")
                return result.stdout
            languages = info(["tesseract", "--list-langs"]).splitlines()
            if any(language not in languages for language in self.settings.cv_ocr_language.split("+")):
                raise OCRReadError("CV OCR language data is unavailable. Install the configured language pack, then retry; no candidate score was assigned.")
            self._identity = {"policy": self.policy(), "tesseract": info(["tesseract", "--version"]).splitlines()[0],
                "renderer": info(["pdftoppm", "-v"]).splitlines()[0]}
        except (OSError, subprocess.SubprocessError, IndexError):
            raise OCRReadError("CV OCR tools could not start. Check the local OCR installation and retry; no candidate score was assigned.") from None
        return self._identity

    def read_page(self, path, page_number, *, deadline):
        identity = self.identity()
        environment = {**os.environ, "OMP_THREAD_LIMIT": "1"}

        def run(args, output=subprocess.DEVNULL):
            remaining = deadline - time.monotonic()
            if remaining <= 0:
                raise OCRReadError("CV OCR exceeded its time limit. Upload a shorter or clearer PDF; no candidate score was assigned.")
            try:
                subprocess.run(args, stdin=subprocess.DEVNULL, stdout=output, stderr=subprocess.DEVNULL,
                    timeout=min(30, remaining), check=True, env=environment)
            except subprocess.TimeoutExpired:
                raise OCRReadError("CV OCR exceeded its time limit. Upload a shorter or clearer PDF; no candidate score was assigned.") from None
            except (OSError, subprocess.SubprocessError):
                raise OCRReadError("CV OCR could not read the scanned page. Upload a clearer scan or text-based PDF/DOCX; no candidate score was assigned.") from None

        # TemporaryDirectory is private and is removed on success and every failure.
        with tempfile.TemporaryDirectory(prefix="hiresense-cv-ocr-") as folder:
            prefix = Path(folder) / "page"
            image_path = prefix.with_suffix(".png")
            run(["pdftoppm", "-f", str(page_number), "-l", str(page_number), "-singlefile", "-r", "200",
                "-scale-to", str(self.settings.cv_ocr_max_image_side), "-gray", "-png", str(path), str(prefix)])
            if not image_path.is_file() or image_path.stat().st_size > 20_000_000:
                raise OCRReadError("CV OCR rendering exceeded its image limit; upload a simpler PDF. No candidate score was assigned.")
            try:
                with Image.open(image_path) as image:
                    if max(image.size) > self.settings.cv_ocr_max_image_side or min(image.size) < 1:
                        raise OCRReadError("CV OCR rendering exceeded its image limit; no candidate score was assigned.")
                    blank = image.convert("L").getextrema() == (255, 255)
            except (OSError, Image.DecompressionBombError):
                raise OCRReadError("CV OCR could not read the rendered page; upload a clearer PDF. No candidate score was assigned.") from None
            if blank:
                return "", {"page": page_number, "blank": True, "identity": identity}
            tsv_path = Path(folder) / "words.tsv"
            with tsv_path.open("wb") as output:
                run(["tesseract", str(image_path), "stdout", "-l", self.settings.cv_ocr_language,
                    "--psm", "3", "tsv"], output)
            if tsv_path.stat().st_size > 8_000_000:
                raise OCRReadError("CV OCR text exceeded its complexity limit; no candidate score was assigned.")
            try:
                tsv = tsv_path.read_text(encoding="utf-8", errors="strict")
            except UnicodeError:
                raise OCRReadError("CV OCR returned unreadable text; retry with a clearer PDF. No candidate score was assigned.") from None
            return self.parse_words(tsv, page_number, identity)

    def parse_words(self, tsv, page_number, identity):
        try:
            words, lines, confidence = [], {}, []
            for row in csv.DictReader(io.StringIO(tsv), delimiter="\t", quoting=csv.QUOTE_NONE):
                if row["level"] != "5" or not row["text"].strip():
                    continue
                word, value = row["text"].strip(), float(row["conf"])
                if not math.isfinite(value) or not 0 <= value <= 100:
                    raise ValueError()
                key = tuple(row[k] for k in ("block_num", "par_num", "line_num"))
                lines.setdefault(key, []).append(word)
                # Punctuation does not swamp confidence of actual letters/numbers.
                weight = sum(character.isalnum() for character in word)
                if weight:
                    confidence.append((value, weight))
                words.append(word)
            text = "\n".join(" ".join(line) for line in lines.values())
            size = sum(weight for _, weight in confidence)
            average = sum(value * weight for value, weight in confidence) / size if size else 0
            uncertain = sum(weight for value, weight in confidence if value < 50) / size if size else 1
            if len(text) > self.settings.cv_max_characters:
                raise OCRReadError("CV OCR text exceeded its complexity limit; no candidate score was assigned.")
            if len(confidence) < 5 or size < 40 or average < self.settings.cv_ocr_min_confidence or uncertain > self.settings.cv_ocr_max_uncertain_ratio:
                raise OCRReadError(f"CV OCR confidence is too low on PDF page {page_number}. Upload a clearer scan or text-based PDF/DOCX; no candidate score was assigned.")
        except (KeyError, TypeError, ValueError, AttributeError, csv.Error) as exc:
            if isinstance(exc, OCRReadError):
                raise
            raise OCRReadError("CV OCR returned unreadable text; retry with a clearer PDF. No candidate score was assigned.") from None
        return text, {"page": page_number, "word_count": len(words), "mean_confidence": round(average, 2),
            "uncertain_character_ratio": round(uncertain, 4), "identity": identity}
