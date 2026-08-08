from __future__ import annotations

import re
import unicodedata


def normalized_text(value: str) -> str:
    """Normalize UI text for adapter-level matching without changing stored copy."""
    value = unicodedata.normalize("NFKC", value).replace("\u00a0", " ")
    return " ".join(value.split()).casefold()


def compact_text(value: str) -> str:
    return " ".join(value.replace("\u00a0", " ").split())


def remove_text_blocks(value: str, blocks: tuple[str, ...]) -> str:
    """Remove known UI blocks while tolerating whitespace and dash variations."""
    cleaned = value
    for block in blocks:
        words = ["[-–—]" if word in {"-", "–", "—"} else re.escape(word) for word in compact_text(block).split()]
        pattern = r"\s*".join(words)
        cleaned = re.sub(pattern, " ", cleaned, flags=re.IGNORECASE)
    cleaned = re.sub(r"\s+([,.;:!?])", r"\1", compact_text(cleaned))
    return re.sub(r"([.!?])\1+", r"\1", cleaned)
