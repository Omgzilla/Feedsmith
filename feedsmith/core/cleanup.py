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
        words = [re.escape(word) for word in compact_text(block).split()]
        pattern = r"\s*".join(words).replace(r"\-", "[-–—]")
        cleaned = re.sub(pattern, " ", cleaned, flags=re.IGNORECASE)
    return compact_text(cleaned)
