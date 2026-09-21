"""Conservative output cleanup."""

from __future__ import annotations


class TextPostprocessor:
    def process(self, raw_text: str, context: str = "") -> str:  # noqa: ARG002
        """Remove model framing whitespace without silently rewriting user content."""
        return raw_text.strip()

