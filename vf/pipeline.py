"""Glue: load -> frame/dates -> clocks -> claims -> judge -> verify -> output."""
import calendar
import sys
from collections import Counter
from typing import Dict, List, Optional

from .claims import extract_claims, report_date
from .clocks import choose_reference, estimate_clocks
from .judge import Ctx, Verdict, judge
from .loaders import decode, load_dir


def _wall(row, frame_off) -> Optional[float]:
    s = row.stamp
    if s is None:
        return None
    if s.kind == "abs":
        off = frame_off if frame_off is not None else s.offset
        return None if off is None else s.seconds + off
    return s.seconds if s.kind in ("naive", "rel") else None   # 'tod' needs a date, handled by caller


def infer_frame(rows) -> Optional[int]:
    """The local UTC offset, only if every zone-bearing timestamp agrees. Otherwise None (we do not guess)."""
    offs = Counter(r.stamp.offset for r in rows if r.stamp and r.stamp.kind == "abs" and r.stamp.offset is not None)
    return next(iter(offs)) if len(offs) == 1 else None


def infer_date(rows, frame_off) -> Optional[float]:
    days = Counter()
    for r in rows:
        w = _wall(r, frame_off)
        if w is not None and r.stamp.kind in ("abs", "naive"):
            days[int(w // 86400) * 86400] += 1
    return days.most_common(1)[0][0] if days else None


def verify(v: Verdict) -> Verdict:
    """Hard gate: a match/conflict is only written if the quote is an exact substring of the cited row's raw text."""
    if v.finding in ("match", "conflict"):
        if v.row is None or not v.quote or v.quote not in v.row.raw:
            return Verdict("not_settled", why="quote failed exact-substring check: downgraded")
    return v


def run(report_path: str, records_dir: str, trace=None) -> dict:
    with open(report_path, "rb") as fh:
        report = decode(fh.read())
    rows, warnings = load_dir(records_dir)
    for w in warnings:
        print("warning:", w, file=sys.stderr)
    frame = infer_frame(rows)
    rd = report_date(report)
    if rd:
        date_base, date_known = float(calendar.timegm((rd[0], rd[1], rd[2], 0, 0, 0, 0, 0, 0))), True
    else:
        d = infer_date(rows, frame)
        date_base, date_known = (d, True) if d is not None else (0.0, False)
    for r in rows:
        r.t = (date_base + r.stamp.seconds) if (r.stamp and r.stamp.kind == "tod") else _wall(r, frame)
    ref = choose_reference(rows)
    clocks = estimate_clocks(rows, ref)
    ctx = Ctx(rows, clocks, date_base, date_known, ref)
    if trace:
        trace(f"reference clock: {ref}; local frame offset: {frame}; date known: {date_known}")
        for k, s in sorted(clocks.items()):
            trace(f"clock {k}: {s.state} c={s.c:g} unc={s.unc:g} {s.reason}")
    findings: List[dict] = []
    for c in extract_claims(report):
        v = verify(judge(c, ctx))
        item: Dict[str, object] = {"claim": c.text, "finding": v.finding}
        if v.finding in ("match", "conflict"):
            item["cite"] = {"file": v.row.file, "row": v.row.row}
            item["quote"] = v.quote
        findings.append(item)
        if trace:
            trace(f"[{v.finding}] {c.text!r} -> {v.why}")
    return {"findings": findings}
