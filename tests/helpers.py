from __future__ import annotations

_UNICODE_DASHES = str.maketrans({"‐": "-", "‑": "-", "‒": "-", "–": "-", "—": "-"})


def norm_text(text: str | None) -> str:
    """Lowercase and fold Unicode dashes (which Groq models emit) to ASCII hyphens."""
    return (text or "").translate(_UNICODE_DASHES).lower()
