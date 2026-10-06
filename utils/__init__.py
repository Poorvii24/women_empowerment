"""
utils/
======
Shared, framework-agnostic helper modules (Tasks 4 & 5 of the
production-readiness pass): standardized API response envelopes and input
validation helpers.

SCOPE NOTE: existing routes already return a `{"status": "ok"|"error",
"message": ...}` shaped JSON body fairly consistently, and the frontend JS
(script.js, career.html's inline script, copilot_widget.js) reads those
exact keys. `responses.py` formalizes and documents that existing
convention rather than introducing a new envelope shape, specifically to
avoid breaking frontend code that depends on the current response keys.
New routes (see the AI Copilot routes) already follow this shape by hand;
`responses.py` is the recommended way to produce it going forward.
"""
