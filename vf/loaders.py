"""One loader per format. Every loader returns Row objects and never raises on bad rows:
a malformed row is kept (so numbering stays stable) but flagged and never used as evidence.
All record text is DATA: nothing here evaluates or obeys it."""
import csv
import json
import os
import re
from typing import List, Tuple

from .models import Row, Stamp, row_number
from .timeparse import parse_stamp

csv.field_size_limit(1 << 26)

_STAMP_COLS = ("timestamp", "time", "ts", "logged", "datetime", "date_time", "logged_at", "recorded", "recorded_at")
_TS_KEYS = {"logged", "timestamp", "time", "ts", "at", "datetime", "created", "date", "logged_at",
            "occurred", "recorded", "recorded_at"}
_NOTE_COLS = ("note", "notes", "text", "comment", "description", "message")
_ID_COLS = ("id", "row", "row_id", "no", "#")
_DEVICE_COLS = ("device", "camera", "cam", "sensor")


def decode(b: bytes) -> str:
    """UTF-8 (BOM tolerated) first; otherwise Windows-1252; last resort latin-1 (never fails)."""
    for enc in ("utf-8-sig", "cp1252"):
        try:
            return b.decode(enc).lstrip("\ufeff")
        except UnicodeDecodeError:
            pass
    return b.decode("latin-1").lstrip("\ufeff")


# ---------------------------------------------------------------- CSV
class _Lines:
    """Line source that tells us how many physical lines the csv reader has consumed."""
    def __init__(self, lines):
        self.lines, self.i = lines, 0

    def __iter__(self):
        return self

    def __next__(self):
        if self.i >= len(self.lines):
            raise StopIteration
        self.i += 1
        return self.lines[self.i - 1]


def _to_float(s):
    try:
        return float(str(s).strip())
    except (ValueError, TypeError):
        return None


def load_csv(name: str, text: str) -> List[Row]:
    lines = re.findall(r"[^\r\n]*(?:\r\n|\n|\r)|[^\r\n]+$", text)
    src = _Lines(lines)
    reader = csv.reader(src)
    rows: List[Row] = []
    header = None
    start = 0
    try:
        for rec in reader:
            end = src.i
            raw = "".join(lines[start:end]).rstrip("\r\n")
            start = end
            if not rec or all(not c.strip() for c in rec):
                continue                                   # blank line
            first = rec[0].lstrip()
            if header is None:
                if first.startswith("#"):
                    continue                               # marker / comment line before the header
                header = [h.strip() for h in rec]
                continue
            if first.startswith("#PLEARUN"):
                continue                                   # stray marker line in the body
            rows.append(_csv_row(name, row_number(len(rows)), raw, header, rec))
    except csv.Error:
        pass                                               # keep what we parsed; the rest is unreadable
    return rows


def _csv_row(name, rownum, raw, header, rec) -> Row:
    low = [h.lower() for h in header]
    fields = dict(zip(header, rec))
    malformed = len(rec) != len(header)
    kind = "table"
    if any(h.startswith("speed") for h in low):
        kind = "camera"
    elif any(h in _NOTE_COLS for h in low):
        kind = "notes"
    stamp_col = next((h for h, l in zip(header, low) if l in _STAMP_COLS), None)
    dev_col = next((h for h, l in zip(header, low) if l in _DEVICE_COLS), None)
    stamp = parse_stamp(fields.get(stamp_col)) if stamp_col else None
    skip = {c for c, l in zip(header, low) if l in _ID_COLS} | {stamp_col}
    if kind == "camera":
        skip.add(dev_col)
    note_col = next((h for h, l in zip(header, low) if l in _NOTE_COLS), None)
    text = fields.get(note_col, "") if note_col else " ".join(v for k, v in fields.items() if k not in skip)
    anchor = " ".join(f"{k} {v}" for k, v in fields.items() if k not in skip)
    clock = f"{name}:{fields.get(dev_col, '').strip()}" if (kind == "camera" and dev_col and fields.get(dev_col, "").strip()) else name
    row = Row(file=name, row=rownum, raw=raw, kind=kind, clock=clock, fields=fields, text=text,
              anchor_text=anchor, stamp=stamp, malformed=malformed)
    row.quote = raw if '"' not in raw else (text if text and text in raw else raw)
    if kind == "camera":
        for h, l in zip(header, low):
            v = _to_float(fields.get(h))
            if l.startswith("speed") and v is not None:
                row.speed_mph = v * (0.621371 if re.search(r"(kph|kmh|km_h|kmph)", l) else 1.0)
            elif l.startswith("zone") and v is not None:
                row.zone_mph = v * (0.621371 if re.search(r"(kph|kmh|km_h|kmph)", l) else 1.0)
    if stamp is None or (kind == "camera" and row.speed_mph is None):
        row.malformed = True                               # unusable as evidence, but still counted in numbering
    return row


# ---------------------------------------------------------------- JSON
class _Scanner:
    """Tiny JSON parser that remembers where every object starts and ends in the file text,
    so the 'raw text of a row' is the exact span of the file (quotes can be verified against it)."""
    _NUM = re.compile(r"-?\d+(?:\.\d+)?(?:[eE][+-]?\d+)?")
    _STR = re.compile(r'"(?:[^"\\]|\\.)*"', re.S)

    def __init__(self, s):
        self.s, self.i, self.nodes = s, 0, []

    def ws(self):
        s, n, i = self.s, len(self.s), self.i
        while i < n and s[i] in " \t\r\n":
            i += 1
        self.i = i

    def value(self, in_list=False):
        self.ws()
        c = self.s[self.i]
        if c == "{":
            return self.obj(in_list)
        if c == "[":
            return self.arr()
        if c == '"':
            return self.string()
        for lit, val in (("true", True), ("false", False), ("null", None)):
            if self.s.startswith(lit, self.i):
                self.i += len(lit)
                return val
        m = self._NUM.match(self.s, self.i)
        if not m:
            raise ValueError("bad json")
        self.i = m.end()
        t = m.group()
        return float(t) if any(ch in t for ch in ".eE") else int(t)

    def string(self):
        m = self._STR.match(self.s, self.i)
        if not m:
            raise ValueError("bad string")
        self.i = m.end()
        return json.loads(m.group())

    def arr(self):
        self.i += 1
        out = []
        self.ws()
        if self.s[self.i] == "]":
            self.i += 1
            return out
        while True:
            out.append(self.value(True))
            self.ws()
            c = self.s[self.i]
            self.i += 1
            if c == ",":
                continue
            if c == "]":
                return out
            raise ValueError("bad array")

    def obj(self, in_list):
        start, slot = self.i, len(self.nodes)
        self.nodes.append(None)                            # reserve slot => document (pre-)order
        self.i += 1
        d = {}
        self.ws()
        if self.s[self.i] == "}":
            self.i += 1
        else:
            while True:
                self.ws()
                k = self.string()
                self.ws()
                if self.s[self.i] != ":":
                    raise ValueError("bad object")
                self.i += 1
                d[k] = self.value(False)
                self.ws()
                c = self.s[self.i]
                self.i += 1
                if c == ",":
                    continue
                if c == "}":
                    break
                raise ValueError("bad object")
        self.nodes[slot] = (start, self.i, d, in_list)
        return d


def _is_ts_key(k: str) -> bool:
    k = k.lower()
    return k in _TS_KEYS or k.endswith("_at") or k.endswith("_time")


def _flat(d: dict, prefix="") -> dict:
    out = {}
    for k, v in d.items():
        if isinstance(v, dict):
            out.update(_flat(v, prefix + k + "."))
        elif not isinstance(v, list):
            out[prefix + k] = v
    return out


def _json_row(name, rownum, raw, d) -> Row:
    fields = _flat(d)
    ts_key = next((k for k in fields if _is_ts_key(k.split(".")[-1])), None)
    stamp = parse_stamp(fields.get(ts_key)) if ts_key else None
    skip = {k for k in fields if k.lower() in _ID_COLS} | {ts_key}
    text = " ".join(str(v).replace("_", " ") for k, v in fields.items() if k not in skip and isinstance(v, str))
    anchor = " ".join(f"{k} {v}" for k, v in fields.items() if k not in skip and v is not None)
    row = Row(file=name, row=rownum, raw=raw, kind="dispatch", clock=name, fields=fields, text=text,
              anchor_text=anchor, stamp=stamp)
    row.quote = str(fields.get(ts_key)) if ts_key else raw
    row.malformed = stamp is None
    return row


def load_json(name: str, text: str) -> List[Row]:
    try:
        sc = _Scanner(text)
        sc.value()
        sc.ws()
        if sc.i != len(text):
            raise ValueError("trailing data")
        spans = [(a, b, d) for (a, b, d, in_list) in sc.nodes if in_list and any(_is_ts_key(k) for k in d)]
        return [_json_row(name, row_number(i), text[a:b], d) for i, (a, b, d) in enumerate(spans)]
    except (ValueError, IndexError, RecursionError):
        pass
    # fallback: stdlib parser; raw text becomes the re-serialised object
    try:
        data = json.loads(text)
    except (ValueError, RecursionError):
        return []                                          # unreadable or absurdly nested: no rows, never a crash
    found, stack = [], [(data, False)]
    while stack:
        node, in_list = stack.pop()
        if isinstance(node, dict):
            if in_list and any(_is_ts_key(k) for k in node):
                found.append(node)
            stack.extend((v, False) for v in reversed(list(node.values())))
        elif isinstance(node, list):
            stack.extend((v, True) for v in reversed(node))
    return [_json_row(name, row_number(i), json.dumps(d, ensure_ascii=False), d) for i, d in enumerate(found)]


# ---------------------------------------------------------------- VTT
_CUE = re.compile(r"^\s*(?:(\d+):)?(\d{1,2}):(\d{2})[.,](\d{3})\s*-->")


def load_vtt(name: str, text: str) -> List[Row]:
    blocks, cur = [], []
    for line in re.split(r"\r\n|\n|\r", text) + [""]:
        if line.strip() == "":
            if cur:
                blocks.append(cur)
                cur = []
        else:
            cur.append(line)
    rows: List[Row] = []
    for block in blocks:
        if block[0].startswith("WEBVTT") or block[0].startswith(("NOTE", "STYLE", "REGION")):
            continue
        k = next((i for i, l in enumerate(block) if "-->" in l), None)
        if k is None:
            continue
        m = _CUE.match(block[k])
        if not m:
            continue
        h = int(m.group(1) or 0)
        start = h * 3600 + int(m.group(2)) * 60 + int(m.group(3)) + int(m.group(4)) / 1000.0
        payload = "\n".join(block[k + 1:])
        plain = re.sub(r"<[^>]+>", "", payload)
        rows.append(Row(file=name, row=row_number(len(rows)), raw=payload, kind="bodycam", clock=name,
                        fields={"start": start, "timing": block[k].strip()}, text=plain, quote=payload,
                        anchor_text=plain, stamp=Stamp("rel", start, 0.001),
                        malformed=not payload.strip()))
    return rows


# ---------------------------------------------------------------- directory
def load_dir(path: str) -> Tuple[List[Row], List[str]]:
    rows: List[Row] = []
    warnings: List[str] = []
    for name in sorted(os.listdir(path)):
        full = os.path.join(path, name)
        ext = os.path.splitext(name)[1].lower()
        if not os.path.isfile(full) or ext not in (".csv", ".json", ".vtt"):
            continue
        try:
            with open(full, "rb") as fh:
                text = decode(fh.read())
            loader = {".csv": load_csv, ".json": load_json, ".vtt": load_vtt}[ext]
            rows.extend(loader(name, text))
        except Exception as exc:                           # one bad file must not kill the run
            warnings.append(f"skipped {name}: {exc!r}")
    return rows, warnings
