"""Decision rules. The asymmetry is deliberate:
  match        needs an agreeing row whose clock is usable for the comparison
  conflict     needs an INSTRUMENT row (camera/dispatch), a usable clock, an unambiguous event,
               and a gap larger than (claim tolerance + clock uncertainty)
  not_settled  everything else that is checkable but not decisive
  not_checkable no machine record could confirm the claim
Notes and transcripts are human-authored: they may support a `match` for an *event/time* claim by
stating the same time in their text, but they can never produce a `conflict`, and they never settle
a measured quantity (speed) - that needs an instrument row."""
from dataclasses import dataclass
from typing import List, Optional, Tuple

from .claims import Claim
from .events import event_of
from .models import Row
from .timeparse import find_clock_times

SPEED_MATCH_MPH = 2.0       # |claimed - measured| <= this -> agrees
SPEED_CONFLICT_MPH = 5.0    # |claimed - measured| >= this -> disagrees (between: not decisive)
DAY = 86400.0


@dataclass
class Verdict:
    finding: str
    row: Optional[Row] = None
    quote: Optional[str] = None
    why: str = ""


def _ns(why): return Verdict("not_settled", why=why)


class Ctx:
    def __init__(self, rows, clocks, date_base, date_known, ref_clock):
        self.rows, self.clocks = rows, clocks
        self.date_base, self.date_known, self.ref_clock = date_base, date_known, ref_clock

    def claim_time(self, c: Claim) -> float:
        return self.date_base + c.tod

    def tdiff(self, a: float, b: float) -> float:
        d = abs(a - b)
        return d if self.date_known else min(d % DAY, DAY - d % DAY)


def _tol(c: Claim) -> float:
    base = max(c.tod_prec, 2.0)
    return base * (2.0 if c.hedged else 1.0)


def ref_time(row: Row, ctx: Ctx, same_clock: bool = False) -> Optional[Tuple[float, float]]:
    """(time in the reference clock, uncertainty) or None when this row's clock cannot be used."""
    if row.t is None or row.stamp is None or row.malformed:
        return None
    half = row.stamp.precision / 2.0
    if same_clock and row.kind == "dispatch":
        return row.t, half
    cs = ctx.clocks.get(row.clock)
    if cs is None or cs.state == "unaligned":
        return None
    return row.t + cs.c, cs.unc + half


def event_rows(ev: str, rows: List[Row]) -> List[Row]:
    out = []
    for r in rows:
        if r.malformed:
            continue
        if r.kind == "camera":
            if ev == "stop" and r.speed_mph == 0:
                out.append(r)
        elif event_of(r.text) == ev:
            out.append(r)
    return sorted(out, key=lambda r: r.key)


def _zone_ambiguous(gap: float, slack: float) -> bool:
    """True if the gap is (nearly) a whole number of quarter-hours, i.e. could be a time-zone difference."""
    k = round(gap / 900.0)
    return 1 <= k <= 56 and abs(gap - k * 900.0) <= slack


def _quote(r: Row) -> str:
    return r.quote or r.raw


def _dedupe(items, keyf):
    seen, out = set(), []
    for it in items:
        k = keyf(it)
        if k not in seen:
            seen.add(k)
            out.append(it)
    return out


# ------------------------------------------------------------------ time of an event
def judge_time_event(c: Claim, ctx: Ctx) -> Verdict:
    if not c.event:
        return _ns("claim mentions a time but no event type we can look up")
    cands = event_rows(c.event, ctx.rows)
    if not cands:
        return _ns(f"no record row describes a '{c.event}' event")
    claim_t, tol = ctx.claim_time(c), _tol(c)
    inst, human, text_hits, unusable = [], [], [], 0
    for r in cands:
        ut = ref_time(r, ctx, c.same_clock)
        if ut:
            t, unc = ut
            d = ctx.tdiff(t, claim_t)
            st = "agree" if d <= tol else ("disagree" if d > tol + unc else "border")
            if st == "disagree" and r.stamp.kind == "naive" and _zone_ambiguous(d, tol + unc):
                st = "border"          # a zone-less stamp may simply be in another time zone: not decisive
            (inst if r.instrument else human).append((r, d, st))
            continue
        unusable += 1
        if not r.instrument:
            for sec, prec in find_clock_times(r.text):           # a time the person wrote in the text itself
                d = min(abs(sec - c.tod), DAY - abs(sec - c.tod))      # both are plain times of day
                text_hits.append((r, d, "agree" if d <= tol else "disagree"))
    inst = _dedupe(inst, lambda x: (x[0].clock, round(x[0].t)))
    if inst:
        ag = [x for x in inst if x[2] == "agree"]
        dis = [x for x in inst if x[2] == "disagree"]
        bd = [x for x in inst if x[2] == "border"]
        if ag and not dis and not bd:
            r = min(ag, key=lambda x: x[1])[0]
            return Verdict("match", r, _quote(r), "instrument row agrees within tolerance")
        if len(inst) == 1 and dis:
            r, d, _ = dis[0]
            return Verdict("conflict", r, _quote(r), f"only instrument row differs by {d:.0f}s (> tolerance {tol:.0f}s + clock uncertainty)")
        return _ns("instrument rows are ambiguous, borderline or disagree with each other")
    hum = human + text_hits
    ag = [x for x in hum if x[2] == "agree"]
    if ag and not [x for x in hum if x[2] != "agree"]:
        r = min(ag, key=lambda x: (x[1], x[0].key))[0]
        txt = r.text if r.text and r.text in r.raw else _quote(r)
        return Verdict("match", r, txt, "no usable instrument clock; the record itself states a matching time (human-authored, not independent)")
    return _ns(f"no row with a usable clock ({unusable} rows on unaligned clocks) and no stated matching time")


# ------------------------------------------------------------------ speed
def judge_speed(c: Claim, ctx: Ctx) -> Verdict:
    if c.tod is None:
        return _ns("speed claim has no time context, so no camera reading can be tied to it")
    cams = [r for r in ctx.rows if r.kind == "camera" and not r.malformed and r.speed_mph is not None]
    if not cams:
        return _ns("no camera speed readings")
    cams = _dedupe(cams, lambda r: (r.clock, round(r.t, 1), r.speed_mph))
    claim_t, tol = ctx.claim_time(c), _tol(c)
    inwin, unaligned = [], 0
    for r in cams:
        ut = ref_time(r, ctx)
        if ut is None:
            unaligned += 1
            continue
        t, unc = ut
        if ctx.tdiff(t, claim_t) <= tol + unc:
            inwin.append(r)
    if not inwin:
        return _ns(f"no camera reading in the time window on an aligned clock ({unaligned} readings are on unaligned clocks)")
    agree = [r for r in inwin if abs(r.speed_mph - c.speed_mph) <= SPEED_MATCH_MPH]
    far = [r for r in inwin if abs(r.speed_mph - c.speed_mph) >= SPEED_CONFLICT_MPH]
    if agree and len(agree) == len(inwin):
        r = min(agree, key=lambda r: abs(r.speed_mph - c.speed_mph))
        if c.zone_mph is not None and r.zone_mph is not None and abs(r.zone_mph - c.zone_mph) > 0.5:
            return _ns("speed agrees but the camera's zone limit differs from the claimed zone")
        return Verdict("match", r, _quote(r), "single/all camera readings in the window agree")
    if len(inwin) == 1 and far:
        r = far[0]
        return Verdict("conflict", r, _quote(r), f"only reading in window is {r.speed_mph:g} mph vs claimed {c.speed_mph:g}")
    return _ns("camera readings in the window are mixed or only mildly different; cannot tie one to this vehicle")


# ------------------------------------------------------------------ duration between two events
def judge_duration(c: Claim, ctx: Ctx) -> Verdict:
    if not c.event or not c.ref_event:
        return _ns("could not identify both events of the duration claim")
    S = _dedupe(event_rows(c.event, ctx.rows), lambda r: (r.clock, round(r.t or 0)))
    R = _dedupe(event_rows(c.ref_event, ctx.rows), lambda r: (r.clock, round(r.t or 0)))
    if len(S) != 1 or len(R) != 1:
        return _ns(f"{len(S)} candidate rows for '{c.event}' and {len(R)} for '{c.ref_event}': need exactly one each")
    rs, rr = S[0], R[0]
    if rs.clock == rr.clock and rs.t is not None and rr.t is not None:
        ts, tr, unc = rs.t, rr.t, (rs.stamp.precision + rr.stamp.precision) / 2.0
    else:
        a, b = ref_time(rs, ctx), ref_time(rr, ctx)
        if a is None or b is None:
            return _ns("the two events are on clocks that are not aligned with each other")
        ts, tr, unc = a[0], b[0], a[1] + b[1]
    diff = (ts - tr) if c.rel in ("after", "later", "following") else (tr - ts)
    tol = max(60.0 if c.hedged else 10.0, 1.0)
    if abs(diff - c.dur_s) <= tol:
        return Verdict("match", rs, _quote(rs), f"measured gap {diff:.0f}s vs claimed {c.dur_s:.0f}s")
    if abs(diff - c.dur_s) > tol + unc and rs.instrument and rr.instrument:
        return Verdict("conflict", rs, _quote(rs), f"measured gap {diff:.0f}s vs claimed {c.dur_s:.0f}s")
    return _ns("gap is not decisive (or an event comes from a human-authored record)")


def judge(c: Claim, ctx: Ctx) -> Verdict:
    if c.kind == "not_checkable":
        return Verdict("not_checkable", why="no quantity a machine record could confirm")
    try:
        if c.kind == "time_event":
            return judge_time_event(c, ctx)
        if c.kind == "speed":
            return judge_speed(c, ctx)
        if c.kind == "duration":
            return judge_duration(c, ctx)
    except Exception as exc:                                  # a bug in one claim must never kill the run
        return _ns(f"internal error handled: {exc!r}")
    return _ns("unknown claim kind")
