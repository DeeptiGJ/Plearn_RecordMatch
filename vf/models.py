"""Shared data model. The row-numbering rule lives in exactly one place: row_number()."""
from dataclasses import dataclass, field
from typing import Optional


def row_number(index0: int) -> int:
    """The ONLY place that decides how rows are numbered.

    Convention (documented in README): 1-based position among *data* rows.
      CSV  : marker line and header are not counted; blank lines are not counted.
      VTT  : cue order (1 = first cue); NOTE/STYLE/REGION blocks are not counted.
      JSON : order of appearance of record objects (objects inside a list that carry a timestamp key).
    """
    return index0 + 1


@dataclass(frozen=True)
class Stamp:
    kind: str                    # 'abs' (instant), 'naive' (wall clock, no zone), 'tod' (time of day only), 'rel' (seconds from recording start)
    seconds: float               # abs: epoch UTC; naive: wall seconds; tod: seconds since midnight; rel: seconds since start
    precision: float             # smallest unit the source can express, in seconds (60 for HH:MM)
    offset: Optional[int] = None  # UTC offset in seconds, only for 'abs' stamps written with a zone


@dataclass
class Row:
    file: str
    row: int
    raw: str                     # the text a quote must be an exact substring of
    kind: str                    # camera | dispatch | notes | bodycam | table
    clock: str                   # which device clock this row was stamped by
    fields: dict = field(default_factory=dict)
    text: str = ""               # human-readable content used for event matching
    quote: str = ""              # default quote (always tried against raw before use)
    anchor_text: str = ""        # text searched for strong anchor tokens (unit ids, plates)
    stamp: Optional[Stamp] = None
    malformed: bool = False
    speed_mph: Optional[float] = None
    zone_mph: Optional[float] = None
    t: Optional[float] = None    # wall-clock seconds in the row's OWN clock (filled by pipeline)

    @property
    def instrument(self) -> bool:
        """Machine-generated sources. Notes and transcripts are human-authored."""
        return self.kind in ("camera", "dispatch")

    @property
    def key(self):
        return (self.file, self.row)
