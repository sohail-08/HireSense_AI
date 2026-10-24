# Local OCR for scanned CVs

PDF parsing keeps selectable text where available. An image-only page, outlined
text page, or a sparse selectable header over a scan uses Poppler rendering and
Tesseract OCR locally. A whole page is transcribed once; native and OCR text are
not concatenated. Mixed PDFs retain each original page's order and block ID.
DOCX processing is unchanged. Original uploads and their checksums never change.

Evidence retains `pdf-page-N` and a `PDF page N (OCR)` locator. Successful screening
stores OCR tool versions, language, page numbers, character-weighted confidence,
uncertain-character ratio and quality policy in extraction metadata and the
screening trace. Quoted evidence is traceable to the transcription and original
page, not a guarantee that every OCR character matches the scan. OCR warnings
instruct the reviewer to verify important details against the original.

## Quality and safety

Default acceptance requires at least five words and 40 characters per nonblank
OCR page, mean character-weighted word confidence of at least 80/100, and at most
15% of alphanumeric characters in words below 50 confidence. These are OCR
quality heuristics, **not** candidate scores or calibrated accuracy probabilities.
Short, unreadable, malformed or low-confidence output stops the whole CV before
any language-model assessment. Blank pages are skipped only when empty PDF
content or an entirely white rendering confirms blankness; failed pages are
never silently dropped from a partially scored CV.

Rendering is bounded to 3500 pixels on the longest side, 20 MB per rendered PNG,
8 MB per TSV, eight OCR pages and 120 seconds total per CV (at most 30 seconds
per render/OCR process). Original upload, page and text limits still apply.
Commands use argument lists without a shell and run as the backend's non-root
user. Private temporary images/TSV files are removed on success and failure.
Subprocess diagnostics, candidate text and file paths are not exposed as errors.
OCR is local; existing embeddings and language-model assessment still follow
their ordinary configured provider workflow after accepted extraction.

The OCR policy and actual tool versions participate in scanned-CV cache identity.
Changed policies do not reuse old OCR evaluations. Native PDF/DOCX engine keys
remain unchanged: adding OCR does not make all readable CVs require rescoring.

## Installation and operation

The backend Docker image installs `poppler-utils`, `tesseract-ocr` and
`tesseract-ocr-eng`. The default OCR language is English (`eng`). For a native
backend, install those tools separately and put `pdftoppm` and `tesseract` on PATH.
Additional languages require their Tesseract data packs and `CV_OCR_LANGUAGE`.
Missing tools/language data fail clearly, without assigning a zero score.

Settings are documented in `.env.example` and forwarded by Docker Compose:
`CV_OCR_ENABLED`, `CV_OCR_LANGUAGE`, `CV_OCR_MIN_CONFIDENCE`,
`CV_OCR_MAX_UNCERTAIN_RATIO`, `CV_OCR_MAX_PAGES`, `CV_OCR_TIMEOUT_SECONDS`,
and `CV_OCR_MAX_IMAGE_SIDE`. Keep conservative thresholds; an unreadable scan
needs a clearer replacement, not artificially relaxed candidate scoring.

Interview scheduling treats a successful OCR provenance notice as advisory only
when its saved page-level trace confirms the quality gate was passed. Other
document warnings, failed/unprocessed CVs and active errors still block selection.
The OCR notice remains visible; it is not deleted to make a candidate eligible.
Normal ranking freshness, recipient validation and invitation confirmation remain
required before any interview or email can be created.

Existing failed scans can be retried using **Rank candidates**. The original
submission need not be uploaded again. Failed runs remain historical; accepted
retries create a new screening and feed the existing evidence/weighted ranking
pipeline. Low-confidence failures remain excluded from numerical rankings.

## Verification

`tests/test_cv_ocr.py` covers word confidence, malformed/empty output, missing
tools, mixed native/scanned pages, sparse headers, page limits, timeouts, private
temporary cleanup and blocking AI calls on extraction failure. The real OCR
round-trip test runs when the local tools are installed, including the Docker
image. Regression tests use synthetic CVs and mocked scoring providers; no live
candidate assessment is fabricated and no provider calls are needed for tests.

Reference: [Tesseract TSV word confidence and line identifiers](https://github.com/tesseract-ocr/tessdoc/blob/main/Command-Line-Usage.md),
[Poppler page rendering options](https://manpages.debian.org/bookworm/poppler-utils/pdftoppm.1.en.html).
