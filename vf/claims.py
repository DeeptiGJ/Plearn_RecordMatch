"""Turn the report text into claims. Pure regex + a few rules: no network, no LLM.
A claim is a clause of the report (the exact text as written). Anything without a checkable
quantity (time, speed, duration) is not_checkable: no machine record could confirm it."""
import re
from dataclasses import dataclass
from typing import List, Optional, Tuple

from .events import event_of
from .timeparse import find_clock_times

HEDGE = re.compile(r"\b(?:about|around|roughly|approximately|approx|circa|nearly|almost)\b|~", re.I)
SPEED = re.compile(r"(\d+(?:\.\d+)?)\s*(mph|miles per hour|km/h|kph|kmh|km per hour)\b", re.I)
ZONE = re.compile(r"\bposted\s+(\d+(?:\.\d+)?)|(\d+(?:\.\d+)?)\s*(?:mph\s*)?(?:zone|speed limit)\b", re.I)
_NUMWORD = {"a": 1, "an": 1, "one": 1, "two": 2, "three": 3, "four": 4, "five": 5, "six": 6, "seven": 7,
            "eight": 8, "nine": 9, "ten": 10, "fifteen": 15, "twenty": 20, "thirty": 30}
DURATION = re.compile(
    r"\b(\d+(?:\.\d+)?|" + "|".join(_NUMWORD) + r")\s*(seconds?|secs?|minutes?|mins?|hours?|hrs?)\s+"
    r"(after|before|later|earlier|following|prior to)\b", re.I)
DATE = re.compile(r"\b(\d{4})-(\d{2})-(\d{2})\b")


@dataclass
class Claim:
    text: str
    kind: str                           # speed | time_event | duration | not_checkable
    tod: Optional[float] = None         # claimed time of day, seconds
    tod_prec: float = 60.0
    hedged: bool = False
    event: Optional[str] = None
    same_clock: bool = False            # "logged at": compare with the logging system's own clock
    speed_mph: Optional[float] = None
    zone_mph: Optional[float] = None
    dur_s: Optional[float] = None
    rel: Optional[str] = None
    ref_event: Optional[str] = None


def report_date(text: str) -> Optional[Tuple[int, int, int]]:
    m = DATE.search(text)
    return (int(m.group(1)), int(m.group(2)), int(m.group(3))) if m else None


def _has_quantity(s: str) -> bool:
    return bool(SPEED.search(s) or DURATION.search(s) or find_clock_times(s))


def _sentences(text: str) -> List[str]:
    out = []
    for line in re.split(r"\r\n|\n|\r", text):
        for s in re.split(r"(?<=[.!?])\s+(?=[A-Z\"'\[])", line.strip()):
            s = s.strip()
            if not s:
                continue
            letters = [c for c in s if c.isalpha()]
            if letters and all(c.isupper() for c in letters):
                continue                                    # banner line, e.g. "SYNTHETIC - FICTIONAL CASE."
            if re.match(r"^Incident\s+\d{4}-\d{2}-\d{2}", s):
                continue                                    # header line
            out.append(s)
    return out


def _clauses(sentence: str) -> List[str]:
    """Split at commas only when BOTH sides carry their own quantity (time/speed/duration)."""
    cuts = [m.start() for m in re.finditer(r",\s+", sentence)]
    bounds = [0] + cuts + [len(sentence)]
    segs = [(bounds[i], bounds[i + 1]) for i in range(len(bounds) - 1)]
    out, cur_s, cur_e = [], segs[0][0], segs[0][1]
    for s, e in segs[1:]:
        cur_text, nxt = sentence[cur_s:cur_e], sentence[s:e]
        if _has_quantity(cur_text) and _has_quantity(nxt):
            out.append(sentence[cur_s:cur_e].strip())
            cur_s = s
            while cur_s < len(sentence) and sentence[cur_s] in ", ":
                cur_s += 1
        cur_e = e
    out.append(sentence[cur_s:cur_e].strip())
    return [c for c in out if c]


def _num(tok: str) -> float:
    return float(_NUMWORD.get(tok.lower(), tok)) if not re.match(r"^\d", tok) else float(tok)


def extract_claims(report_text: str) -> List[Claim]:
    claims: List[Claim] = []
    for sentence in _sentences(report_text):
        ctx = None                                          # time context carried within one sentence
        for clause in _clauses(sentence):
            c = _classify(clause, ctx)
            if c.tod is not None and c.kind != "speed":
                ctx = (c.tod, c.tod_prec, c.hedged)
            claims.append(c)
    return claims


def _classify(text: str, ctx) -> Claim:
    hedged = bool(HEDGE.search(text))
    dur = DURATION.search(text)
    if dur:
        unit = dur.group(2).lower()
        mult = 1 if unit.startswith("sec") else 3600 if unit.startswith(("hour", "hr")) else 60
        return Claim(text, "duration", hedged=hedged, dur_s=_num(dur.group(1)) * mult, rel=dur.group(3).lower(),
                     event=event_of(text[:dur.start()]), ref_event=event_of(text[dur.end():]))
    times = find_clock_times(text)
    sp = SPEED.search(text)
    if sp:
        mph = float(sp.group(1)) * (1.0 if sp.group(2).lower().startswith(("mph", "miles")) else 0.621371)
        z = ZONE.search(text)
        zone = None
        if z:
            zv = float(z.group(1) or z.group(2))
            zone = zv * (0.621371 if re.search(r"km|kph", text[z.start():z.end() + 8], re.I) else 1.0)
        tod, prec, hg = (times[0][0], times[0][1], hedged) if times else (ctx if ctx else (None, 60.0, hedged))
        return Claim(text, "speed", tod=tod, tod_prec=prec, hedged=hg, speed_mph=mph, zone_mph=zone)
    if times:
        return Claim(text, "time_event", tod=times[0][0], tod_prec=times[0][1], hedged=hedged,
                     event=event_of(text), same_clock=bool(re.search(r"\blogged\b", text, re.I)))
    return Claim(text, "not_checkable")
