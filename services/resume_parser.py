"""
services/resume_parser.py
============================
Extracts raw text from an uploaded resume (PDF or DOCX) and splits it into
labeled sections (Skills / Projects / Education / Experience) using
heuristic header-line detection.

Honest scope note: this is a RULE-BASED parser (regex + heading detection),
not a trained resume-parsing model. Real-world resumes vary enormously in
layout, so this won't be perfect on every resume — but it's deterministic,
fast, fully explainable, and good enough to extract a "skills" section for
the gap-analysis comparison, which is the actual goal. If a resume has no
detectable section headers at all, the whole document is treated as one
"Experience" blob so downstream code always has *something* to work with
rather than failing.
"""
import io
import logging
import re

from flask_babel import gettext as _

logger = logging.getLogger("isis.services.resume_parser")

ALLOWED_EXTENSIONS = {"pdf", "docx"}
MAX_FILE_SIZE_BYTES = 8 * 1024 * 1024  # 8MB — generous for a text resume, blocks abuse

# Section header patterns. Order matters: more specific section names are
# checked before generic ones. Matched case-insensitively against a line
# that is short (a heading, not a paragraph) and not deep within a bullet.
_SECTION_PATTERNS = {
    "skills": re.compile(r"^\s*(technical\s+)?skills?\b", re.IGNORECASE),
    "projects": re.compile(r"^\s*(academic\s+)?projects?\b", re.IGNORECASE),
    "education": re.compile(r"^\s*education\b", re.IGNORECASE),
    "experience": re.compile(
        r"^\s*(work\s+)?(experience|employment|internships?)\b", re.IGNORECASE
    ),
    "certifications": re.compile(r"^\s*(certifications?|licenses?)\b", re.IGNORECASE),
}

# A line is considered a "header" if it's short, mostly alphabetic, and
# matches one of the section patterns above — this avoids misfiring on a
# bullet point that happens to start with e.g. "Skills used:".
_MAX_HEADER_LINE_LENGTH = 40


class ResumeParseError(Exception):
    """Raised for any unrecoverable resume parsing failure (corrupt file, unsupported format)."""


def validate_upload(filename: str, file_bytes: bytes) -> str:
    """
    Validates an uploaded resume file before parsing. Returns the lowercase
    extension ('pdf' or 'docx') on success, raises ResumeParseError otherwise.
    """
    if not filename or "." not in filename:
        raise ResumeParseError(_("File has no extension. Please upload a .pdf or .docx file."))

    ext = filename.rsplit(".", 1)[-1].lower()
    if ext not in ALLOWED_EXTENSIONS:
        raise ResumeParseError(_("Unsupported file type '.%(ext)s'. Please upload a .pdf or .docx file.", ext=ext))

    if not file_bytes:
        raise ResumeParseError(_("Uploaded file is empty."))

    if len(file_bytes) > MAX_FILE_SIZE_BYTES:
        raise ResumeParseError(_(
            "File is too large (%(size)sMB). Maximum size is %(max_size)sMB.",
            size=f"{len(file_bytes) / 1024 / 1024:.1f}",
            max_size=f"{MAX_FILE_SIZE_BYTES / 1024 / 1024:.0f}",
        ))

    return ext


def extract_text(file_bytes: bytes, ext: str) -> str:
    """
    Extracts raw text from a PDF or DOCX file's bytes.
    Raises ResumeParseError on a corrupt/unreadable file, never lets the
    underlying library's raw exception escape (those vary wildly in type
    between pypdf and python-docx and aren't meaningful to a caller).
    """
    try:
        if ext == "pdf":
            return _extract_pdf_text(file_bytes)
        elif ext == "docx":
            return _extract_docx_text(file_bytes)
        else:
            raise ResumeParseError(_("Unsupported extension: %(ext)s", ext=ext))
    except ResumeParseError:
        raise
    except Exception as e:
        logger.exception("resume_text_extraction_failed", extra={"ext": ext})
        raise ResumeParseError(_(
            "Could not read the %(ext)s file — it may be corrupted, password-protected, "
            "or an image-only scan with no extractable text.",
            ext=ext.upper(),
        )) from e


def _extract_pdf_text(file_bytes: bytes) -> str:
    from pypdf import PdfReader

    reader = PdfReader(io.BytesIO(file_bytes))
    if reader.is_encrypted:
        raise ResumeParseError(_("This PDF is password-protected. Please upload an unprotected version."))

    pages_text = [page.extract_text() or "" for page in reader.pages]
    text = "\n".join(pages_text).strip()
    if not text:
        raise ResumeParseError(_(
            "No text could be extracted from this PDF — it may be a scanned image rather than "
            "actual text. Try uploading a DOCX version instead."
        ))
    return text


def _extract_docx_text(file_bytes: bytes) -> str:
    import docx

    document = docx.Document(io.BytesIO(file_bytes))
    paragraphs = [p.text for p in document.paragraphs]

    # Tables are common in resume layouts (e.g. skills laid out in a grid) —
    # without this, that content would silently disappear.
    for table in document.tables:
        for row in table.rows:
            for cell in row.cells:
                if cell.text.strip():
                    paragraphs.append(cell.text)

    text = "\n".join(p for p in paragraphs if p.strip())
    if not text.strip():
        raise ResumeParseError(_("No text could be extracted from this DOCX file."))
    return text


def parse_sections(raw_text: str) -> dict:
    """
    Splits raw resume text into labeled sections based on detected headers.

    Returns a dict with keys: skills, projects, education, experience,
    certifications, other — each a single string (possibly empty) containing
    the text under that heading. `other` collects any text before the first
    recognized header (e.g. name/contact info) plus content under headers we
    don't specifically track.

    If NO section headers are detected at all, the entire text is placed
    under "experience" as a reasonable single fallback bucket, rather than
    returning all-empty sections.
    """
    lines = raw_text.splitlines()
    sections = {"skills": [], "projects": [], "education": [], "experience": [], "certifications": [], "other": []}
    current = "other"
    any_header_found = False

    for line in lines:
        stripped = line.strip()
        if not stripped:
            continue

        matched_section = _match_header(stripped)
        if matched_section:
            current = matched_section
            any_header_found = True
            continue  # don't include the header line itself in the section body

        sections[current].append(stripped)

    if not any_header_found:
        # No headers detected at all — treat the whole resume as one
        # "experience" blob so the skill gap engine still has text to work with.
        sections["experience"] = lines
        sections["other"] = []

    return {key: "\n".join(value).strip() for key, value in sections.items()}


def _match_header(line: str) -> str | None:
    """Returns the matched section name if `line` looks like a section heading, else None."""
    if len(line) > _MAX_HEADER_LINE_LENGTH:
        return None  # too long to be a heading — it's body text
    for section_name, pattern in _SECTION_PATTERNS.items():
        if pattern.match(line):
            return section_name
    return None


def extract_candidate_skill_phrases(skills_section_text: str) -> list[str]:
    """
    Splits the "skills" section's raw text into individual candidate skill
    phrases, for embedding-based comparison in skill_gap_engine.py.

    Resumes format skills lists inconsistently (comma-separated, bullet
    points, pipe-separated, newline-separated) — this handles the common
    variants by splitting on commas, bullets, pipes, and semicolons, then
    falling back to newlines if nothing else split the text usefully.
    """
    if not skills_section_text.strip():
        return []

    # Normalize common bullet/separator characters to commas first
    normalized = re.sub(r"[•·▪\u2022]", ",", skills_section_text)
    normalized = re.sub(r"[|;]", ",", normalized)

    raw_phrases = re.split(r"[,\n]", normalized)
    phrases = [p.strip(" -\t") for p in raw_phrases]
    phrases = [p for p in phrases if p and len(p) >= 2]

    return phrases


def parse_resume(filename: str, file_bytes: bytes) -> dict:
    """
    Full pipeline entry point: validates, extracts text, and parses into
    sections + candidate skill phrases. This is what app.py calls.

    Returns:
        {
            "raw_text": str,
            "sections": {"skills": str, "projects": str, ...},
            "candidate_skills": list[str],
        }
    Raises ResumeParseError with a user-facing message on any failure.
    """
    ext = validate_upload(filename, file_bytes)
    raw_text = extract_text(file_bytes, ext)
    sections = parse_sections(raw_text)
    candidate_skills = extract_candidate_skill_phrases(sections["skills"])

    return {
        "raw_text": raw_text,
        "sections": sections,
        "candidate_skills": candidate_skills,
    }
