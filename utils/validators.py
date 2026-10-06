"""
utils/validators.py
====================
Reusable input validation helpers (Task 5).

SCOPE NOTE: resume upload validation (file extension, 8MB size cap, empty-
file check, password-protected PDF detection) already exists and works
inside services/resume_parser.py — it was NOT duplicated or replaced here.
`validate_file_upload()` below is a generic, reusable version of the same
pattern for any *future* upload endpoint, and the Copilot's message-length
check (previously an inline `if len(message) > 2000` in app.py) was
migrated to use `validate_string_length()` here as the first real adopter.
"""

import html
import re

from flask_babel import gettext as _

ALLOWED_RESUME_EXTENSIONS = {"pdf", "docx"}
MAX_RESUME_SIZE_BYTES = 8 * 1024 * 1024  # matches services/resume_parser.py


class ValidationError(Exception):
    """Raised by validators below; carries a user-facing message."""

    def __init__(self, message, field=None):
        super().__init__(message)
        self.message = message
        self.field = field


def require_fields(data: dict, required: list[str]):
    """Raises ValidationError listing every missing/blank required field at
    once (rather than stopping at the first one), for a clearer error message."""
    missing = [f for f in required if not str(data.get(f, "")).strip()]
    if missing:
        raise ValidationError(_("Missing required field(s): %(fields)s.", fields=", ".join(missing)))


def validate_string_length(value: str, field_name: str, max_length: int, min_length: int = 0):
    value = (value or "").strip()
    if len(value) < min_length:
        raise ValidationError(
            _("%(field)s must be at least %(min_length)s character(s).", field=field_name, min_length=min_length),
            field=field_name,
        )
    if len(value) > max_length:
        raise ValidationError(
            _("%(field)s must be %(max_length)s characters or fewer.", field=field_name, max_length=max_length),
            field=field_name,
        )
    return value


def validate_file_upload(
    filename: str, file_bytes: bytes, allowed_extensions=ALLOWED_RESUME_EXTENSIONS, max_size_bytes=MAX_RESUME_SIZE_BYTES
):
    """Generic reusable file-upload validator (extension + size + non-empty).
    See resume_parser.parse_resume() for the resume-specific version of this
    same check, which additionally validates the file can actually be
    parsed (not corrupt, not password-protected)."""
    if not filename or "." not in filename:
        raise ValidationError(_("File has no extension."))
    ext = filename.rsplit(".", 1)[-1].lower()
    if ext not in allowed_extensions:
        raise ValidationError(
            _(
                "Unsupported file type '.%(ext)s'. Allowed: %(allowed)s.",
                ext=ext,
                allowed=", ".join(sorted(allowed_extensions)),
            )
        )
    if not file_bytes:
        raise ValidationError(_("Uploaded file is empty."))
    if len(file_bytes) > max_size_bytes:
        raise ValidationError(_("File is too large (max %(max_mb)sMB).", max_mb=max_size_bytes // (1024 * 1024)))


def sanitize_plain_text(text: str) -> str:
    """
    Defense-in-depth HTML-escaping for any user-supplied text that might ever
    be rendered outside of Jinja's auto-escaping context (e.g. concatenated
    into a JSON field later re-rendered as raw HTML by client-side JS, or a
    log message). Jinja templates in this app already auto-escape by
    default, so this is a belt-and-suspenders helper for non-template
    contexts, not a fix for a known XSS hole.
    """
    if not text:
        return text
    return html.escape(text, quote=True)


_USERNAME_RE = re.compile(r"^[A-Za-z0-9_.-]{3,32}$")


def validate_username(username: str):
    username = (username or "").strip()
    if not _USERNAME_RE.match(username):
        raise ValidationError(
            _("Username must be 3-32 characters and contain only letters, numbers, dots, " "underscores, or hyphens.")
        )
    return username
