"""
utils/responses.py
===================
Standardized API response helpers (Task 4).

Formalizes the JSON envelope ISIS's routes already use:
    {"status": "ok", ...data}
    {"status": "error", "message": "...", ...extra}

These helpers don't change what any existing route returns — they exist so
new routes produce a consistent shape without hand-rolling jsonify() calls,
and so the shape is documented in exactly one place.
"""

from flask import jsonify


def success(data: dict | None = None, message: str | None = None, status_code: int = 200):
    """Builds a standardized success response: {"status": "ok", ...data}."""
    body = {"status": "ok"}
    if message:
        body["message"] = message
    if data:
        body.update(data)
    return jsonify(body), status_code


def error(message: str, status_code: int = 400, errors: dict | None = None):
    """Builds a standardized error response: {"status": "error", "message": "..."}.
    `errors` (optional) carries field-level validation detail, e.g.
    {"email": "This field is required."} for a 422 validation failure."""
    body = {"status": "error", "message": message}
    if errors:
        body["errors"] = errors
    return jsonify(body), status_code


def validation_error(errors: dict):
    """422 Unprocessable Entity — one or more input fields failed validation."""
    return error("Validation failed.", status_code=422, errors=errors)


def unauthorized(message: str = "Authentication required."):
    return error(message, status_code=401)


def forbidden(message: str = "You don't have permission to do that."):
    return error(message, status_code=403)


def not_found(message: str = "Not found."):
    return error(message, status_code=404)


def server_error(message: str = "Something went wrong. Please try again."):
    return error(message, status_code=500)
