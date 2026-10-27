"""Structural validation of a versioned JSONL capture."""

from __future__ import annotations

import hashlib
from pathlib import Path

from .models import SCHEMA_VERSION, CaptureFormatError, parse_line
from .replay import replay_capture


def file_sha256(lines: list[str]) -> str:
    digest = hashlib.sha256()
    for line in lines:
        digest.update(line.encode("utf-8"))
        digest.update(b"\n")
    return digest.hexdigest()


def validate_capture(path: Path | str) -> dict:
    """Validate schema, footer hash, and order-book continuity.

    Raises ``CaptureFormatError`` or ``FileNotFoundError`` for structural
    problems. The returned replay report may still be unsynchronized; the
    CLI maps that to a non-zero exit without calling it a format error.
    """
    source = Path(path)
    if not source.is_file():
        raise FileNotFoundError(f"capture not found: {source}")
    text = source.read_text(encoding="utf-8")
    raw_lines = text.splitlines()
    content = [line for line in raw_lines if line.strip() != ""]
    if not content:
        raise CaptureFormatError("capture is empty")
    header = parse_line(content[0])
    if header.get("type") != "header" or header.get("version") != SCHEMA_VERSION:
        raise CaptureFormatError("first record must be a version 1 header")

    footer = None
    body = content
    last = parse_line(content[-1])
    if last.get("type") == "footer":
        footer = last
        body = content[:-1]
        if footer.get("status") != "complete":
            raise CaptureFormatError(
                f"capture status is {footer.get('status')!r}, expected 'complete'"
            )
        expected = footer.get("content_sha256")
        if not isinstance(expected, str) or len(expected) != 64:
            raise CaptureFormatError("footer content_sha256 is missing")
        actual = file_sha256(body)
        if actual != expected:
            raise CaptureFormatError("content_sha256 does not match the capture body")
    elif any(parse_line(line).get("type") == "footer" for line in content):
        raise CaptureFormatError("footer is not the last record")

    for line in body:
        parse_line(line)
    report = replay_capture(source)
    report["sha256_checked"] = footer is not None
    return report
