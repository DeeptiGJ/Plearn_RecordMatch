"""Clock alignment. Device clocks are NOT synchronized and nobody tells us the offsets.

We only estimate an offset from *anchors*: a strong token (unit id like L-12, or a plate) that
appears in two different clocks, exactly once (per event type) in each. A pair of clocks is
aligned only if >= 2 independent anchors agree within their precision. Offsets are propagated
from a reference clock through the pair graph and each clock carries an uncertainty.
Anything we cannot estimate reliably stays 'unaligned' and is never compared with other clocks."""
import re
import statistics
from dataclasses import dataclass
from typing import Dict, List, Tuple

from .events import event_of
from .models import Row

INF = float("inf")
_TOKEN = re.compile(r"\b[A-Z]{1,4}-\d{1,6}\b")
_PLATE = re.compile(r"(?i:\bplate)\s*(?:(?i:number|no\.?)|#|(?i:is)|:)?\s*([A-Z0-9]{2,4}[- ]?[A-Z0-9]{2,5})\b")


@dataclass
class ClockState:
    state: str            # 'ref' | 'aligned' | 'unaligned'
    c: float = 0.0        # add c to a time on this clock to get reference time
    unc: float = INF      # +/- seconds
    reason: str = ""


def _tokens(row: Row) -> set:
    toks = set(_TOKEN.findall(row.anchor_text))
    for m in _PLATE.finditer(row.anchor_text):
        p = re.sub(r"[\s-]", "", m.group(1)).upper()
        if re.search(r"\d", p) and re.search(r"[A-Z]", p):   # 'unknown' etc. are not plates
            toks.add("PLATE:" + p)
    return toks


def choose_reference(rows: List[Row]) -> str:
    """Prefer the dispatch (CAD) system as the reference clock; otherwise the busiest clock."""
    counts: Dict[str, int] = {}
    for r in rows:
        counts[r.clock] = counts.get(r.clock, 0) + (1000000 if r.kind == "dispatch" else 1)
    return max(sorted(counts), key=lambda c: counts[c]) if counts else ""


def _same_event(rs: List[Row]) -> bool:
    return all(abs(r.t - rs[0].t) <= max(r.stamp.precision, rs[0].stamp.precision, 1.0) for r in rs)


def _edges(rows: List[Row]) -> Dict[Tuple[str, str], Tuple[float, float, int]]:
    index: Dict[object, Dict[str, List[Row]]] = {}
    for r in rows:
        if r.t is None or r.malformed or r.stamp is None:
            continue
        ev = event_of(r.text)
        for tok in _tokens(r):
            index.setdefault(tok, {}).setdefault(r.clock, []).append(r)
            if ev:
                index.setdefault((tok, ev), {}).setdefault(r.clock, []).append(r)
    obs: Dict[Tuple[str, str], Dict[Tuple, Tuple[float, float]]] = {}
    for byclock in index.values():
        uniq = {c: rs[0] for c, rs in byclock.items() if _same_event(rs)}   # ambiguous tokens are dropped
        names = sorted(uniq)
        for i, a in enumerate(names):
            for b in names[i + 1:]:
                ra, rb = uniq[a], uniq[b]
                obs.setdefault((a, b), {})[(ra.key, rb.key)] = (ra.t - rb.t, ra.stamp.precision + rb.stamp.precision)
    edges = {}
    for (a, b), items in obs.items():
        vals = list(items.values())
        if len(vals) < 2:
            continue
        med = statistics.median(d for d, _ in vals)
        inl = [(d, p) for d, p in vals if abs(d - med) <= max(5.0, p)]
        if len(inl) < 2 or len(inl) * 2 <= len(vals):
            continue                                        # anchors disagree: do not align
        ds = [d for d, _ in inl]
        e = statistics.median(ds)
        unc = max((max(ds) - min(ds)) / 2.0, max(p for _, p in inl) / 2.0)
        edges[(a, b)] = (e, unc, len(inl))
        edges[(b, a)] = (-e, unc, len(inl))
    return edges


def _bfs(clocks, ref, edges):
    st = {c: ClockState("unaligned", reason="no reliable anchors") for c in clocks}
    if ref not in st:
        return st
    st[ref] = ClockState("ref", 0.0, 0.0)
    queue = [ref]
    while queue:
        x = queue.pop(0)
        for (a, y), (e, u, n) in sorted(edges.items()):
            if a == x and st[y].state == "unaligned":
                st[y] = ClockState("aligned", st[x].c + e, st[x].unc + u, f"{n} anchors")
                queue.append(y)
    return st


def estimate_clocks(rows: List[Row], ref: str) -> Dict[str, ClockState]:
    clocks = {r.clock for r in rows}
    edges = _edges(rows)
    culprits = set()
    for _ in range(len(clocks) + 1):
        st = _bfs(clocks, ref, edges)
        bad = [(a, b) for (a, b), (e, u, n) in edges.items()
               if st[a].state != "unaligned" and st[b].state != "unaligned"
               and abs((st[b].c - st[a].c) - e) > st[a].unc + st[b].unc + u + 1e-6]
        if not bad:
            break
        # two paths disagree about the same clock: trust neither, refuse to align the clocks involved
        culprits |= {x for pair in bad for x in pair} - {ref}
        edges = {k: v for k, v in edges.items() if k[0] not in culprits and k[1] not in culprits}
    for c in culprits:
        st[c] = ClockState("unaligned", reason="inconsistent anchors")
    return st
