"""Capture records and JSONL parsing.

Schema version 1. Unknown fields are ignored. Required fields are
checked. Prices and quantities in the file are exchange strings; engines
canonicalize them when applying.
"""

from __future__ import annotations

import json

SCHEMA_VERSION = 1
INT64_MAX = 2**63 - 1


class CaptureFormatError(ValueError):
    pass


class UnsupportedSchemaError(CaptureFormatError):
    """The file declares a schema this tool cannot read."""


def dumps(record: dict) -> str:
    return json.dumps(record, separators=(",", ":"), ensure_ascii=False)


def parse_line(line: str) -> dict:
    try:
        data = json.loads(line)
    except json.JSONDecodeError as exc:
        raise CaptureFormatError(f"invalid JSON: {exc}") from exc
    if not isinstance(data, dict):
        raise CaptureFormatError("JSONL record must be an object")
    kind = data.get("type")
    if kind == "header":
        _require_version(data)
        _require_str(data, "symbol")
        _require_str(data, "market")
        return data
    if kind == "footer":
        _require_version(data)
        _require_str(data, "status")
        return data
    if kind == "snapshot":
        _require_i64(data, "last_update_id")
        _require_levels(data, "bids")
        _require_levels(data, "asks")
        return data
    if kind == "depth":
        _require_i64(data, "U")
        _require_i64(data, "u")
        _require_levels(data, "b")
        _require_levels(data, "a")
        return data
    if kind == "agg_trade":
        _require_i64(data, "a")
        _require_str(data, "p")
        _require_str(data, "q")
        return data
    raise CaptureFormatError(f"unknown record type: {kind!r}")


def levels_of(record: dict, key: str) -> list[tuple[str, str]]:
    return [(level[0], level[1]) for level in record[key]]


def _require_version(data: dict) -> None:
    version = data.get("version")
    if isinstance(version, bool) or not isinstance(version, int):
        raise CaptureFormatError("version must be an integer")
    if version != SCHEMA_VERSION:
        raise UnsupportedSchemaError(f"unsupported schema version: {version}")


def _require_str(data: dict, key: str) -> None:
    value = data.get(key)
    if not isinstance(value, str) or value == "":
        raise CaptureFormatError(f"{key} must be a non-empty string")


def _require_i64(data: dict, key: str) -> None:
    value = data.get(key)
    if isinstance(value, bool) or not isinstance(value, int):
        raise CaptureFormatError(f"{key} must be an integer")
    if value < 0 or value > INT64_MAX:
        raise CaptureFormatError(f"{key} is outside uint63 range")


def _require_levels(data: dict, key: str) -> None:
    value = data.get(key)
    if not isinstance(value, list):
        raise CaptureFormatError(f"{key} must be a list")
    for level in value:
        if (
            not isinstance(level, list)
            or len(level) < 2
            or not isinstance(level[0], str)
            or not isinstance(level[1], str)
        ):
            raise CaptureFormatError(f"{key} levels must be [price, quantity] strings")


def as_jsonable(value: Any) -> Any:
    return value
