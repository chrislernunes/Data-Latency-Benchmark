"""Exact decimal strings for prices and quantities.

Canonical form has no exponent, no leading integer zeros (except zero
itself), no trailing fractional zeros, and no decimal point when the
fractional part is empty. Zero is ``"0"``.
"""

from __future__ import annotations


class DecimalFormatError(ValueError):
    """A price or quantity is not a finite non-negative decimal string."""


def canonical_decimal(value: object) -> str:
    """Return the canonical decimal string for ``value``.

    Accepts digit strings with at most one decimal point. Rejects empty
    input, signs, exponents, whitespace, and non-finite tokens such as
    ``NaN`` or ``Infinity``.
    """
    if isinstance(value, bool) or not isinstance(value, str):
        raise DecimalFormatError(f"decimal must be a string, got {type(value).__name__}")
    if value == "" or any(c not in "0123456789." for c in value):
        raise DecimalFormatError(f"malformed decimal: {value!r}")
    if value.count(".") > 1 or value[0] == "." or value[-1] == ".":
        raise DecimalFormatError(f"malformed decimal: {value!r}")
    if "." in value:
        integer, frac = value.split(".", 1)
    else:
        integer, frac = value, ""
    if integer == "" or not integer.isdigit():
        raise DecimalFormatError(f"malformed decimal: {value!r}")
    integer = integer.lstrip("0") or "0"
    frac = frac.rstrip("0")
    if frac:
        return f"{integer}.{frac}"
    return integer


def is_zero(canonical: str) -> bool:
    return canonical == "0"


def compare_decimal(left: str, right: str) -> int:
    """Compare two canonical decimals. Returns -1, 0, or 1."""

    def parts(value: str) -> tuple[str, str]:
        if "." in value:
            integer, frac = value.split(".", 1)
            return integer, frac
        return value, ""

    li, lf = parts(left)
    ri, rf = parts(right)
    if len(li) != len(ri):
        return -1 if len(li) < len(ri) else 1
    if li != ri:
        return -1 if li < ri else 1
    width = max(len(lf), len(rf))
    for index in range(width):
        lc = lf[index] if index < len(lf) else "0"
        rc = rf[index] if index < len(rf) else "0"
        if lc != rc:
            return -1 if lc < rc else 1
    return 0
