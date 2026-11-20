"""Timestamp parsing. Four kinds of stamp, never silently mixed:
abs   - an instant (epoch s/ms/us/ns, or ISO-8601 with a zone)
naive - wall-clock date+time with NO zone (we do not guess the zone)
tod   - time of day only (HH:MM[:SS])
rel   - seconds from a recording start (WebVTT)
"""
import calendar
import re
from typing import List, Optional, Tuple

from .models import Stamp

_ISO = re.compile(
    r"^(\d{4})-(\d{2})-(\d{2})[T ](\d{2}):(\d{2})(?::(\d{2})(?:[.,](\d+))?)?\s*(Z|z|[+-]\d{2}(?::?\d{2})?)?$")
_TOD = re.compile(r"^(\d{1,2}):(\d{2})(?::(\d{2}))?\s*([ap]\.?m\.?)?$", re.I)
_NUM = re.compile(r"^-?\d+(?:\.\d+)?$")
TIME_IN_TEXT = re.compile(r"(?<![\d:])([01]?\d|2[0-3]):([0-5]\d)(?::([0-5]\d))?(?![\d:])\s*([ap]\.?m\.?)?", re.I)


def _epoch(v: float) -> Optional[Tuple[float, float]]:
    a = abs(v)
    if a >= 1e17:
        return v / 1e9, 1e-9
    if a >= 1e14:
        return v / 1e6, 1e-6
    if a >= 1e11:
        return v / 1e3, 1e-3
    if a >= 1e9:
        return v, 1.0
    return None                    # small numbers are not timestamps: refuse to guess


def _tz(s: Optional[str]) -> Optional[int]:
    if s is None:
        return None
    if s in ("Z", "z"):
        return 0
    sign = -1 if s[0] == "-" else 1
    digits = s[1:].replace(":", "")
    h = int(digits[:2])
    m = int(digits[2:4]) if len(digits) >= 4 else 0
    return sign * (h * 3600 + m * 60)


def _tod_seconds(h: int, m: int, s: int, ampm: Optional[str]) -> Optional[int]:
    if ampm:
        if not 1 <= h <= 12:
            return None
        h = h % 12 + (12 if ampm.lower().startswith("p") else 0)
    if h > 23:
        return None
    return h * 3600 + m * 60 + s


def parse_stamp(value) -> Optional[Stamp]:
    if value is None or isinstance(value, bool):
        return None
    if isinstance(value, (int, float)):
        e = _epoch(float(value))
        return Stamp("abs", e[0], e[1]) if e else None
    s = str(value).strip()
    if not s:
        return None
    if _NUM.match(s):
        e = _epoch(float(s))
        return Stamp("abs", e[0], e[1]) if e else None
    m = _ISO.match(s)
    if m:
        y, mo, d, h, mi = (int(m.group(i)) for i in range(1, 6))
        sec = int(m.group(6)) if m.group(6) else 0
        frac = float("0." + m.group(7)) if m.group(7) else 0.0
        if not (1 <= mo <= 12 and 1 <= d <= 31 and 0 <= h < 24 and 0 <= mi < 60 and 0 <= sec < 61):
            return None
        try:
            wall = calendar.timegm((y, mo, d, h, mi, sec, 0, 0, 0)) + frac
        except (ValueError, OverflowError):
            return None
        prec = 60.0 if m.group(6) is None else (1.0 if not m.group(7) else 10.0 ** -len(m.group(7)))
        off = _tz(m.group(8))
        if off is None:
            return Stamp("naive", wall, prec)
        return Stamp("abs", wall - off, prec, off)
    m = _TOD.match(s)
    if m:
        if int(m.group(2)) > 59 or (m.group(3) and int(m.group(3)) > 59):
            return None
        sec = _tod_seconds(int(m.group(1)), int(m.group(2)), int(m.group(3) or 0), m.group(4))
        if sec is None:
            return None
        return Stamp("tod", float(sec), 60.0 if m.group(3) is None else 1.0)
    return None


def find_clock_times(text: str) -> List[Tuple[float, float]]:
    """Clock times written inside free text, e.g. 'about 21:16' -> [(76560.0, 60.0)]."""
    out = []
    for m in TIME_IN_TEXT.finditer(text):
        sec = _tod_seconds(int(m.group(1)), int(m.group(2)), int(m.group(3) or 0), m.group(4))
        if sec is not None:
            out.append((float(sec), 60.0 if m.group(3) is None else 1.0))
    return out
