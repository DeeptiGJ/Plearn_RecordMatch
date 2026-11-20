"""A deliberately small, explicit vocabulary of event types. Used to decide which record rows
describe the same kind of event as a claim. First matching pattern wins (order matters)."""
import re
from typing import Optional

EVENTS = [
    ("911_call", re.compile(r"\b911\b|\bcall(?:er)?\b")),
    ("unit_on_scene", re.compile(r"\bon[ _]scene\b|\barriv")),
    ("unit_dispatched", re.compile(r"\bdispatched\b")),
    ("stop", re.compile(r"\bstop(?:s|ped|ping)?\b|\bpull(?:ed|ing)\s+(?:in|into|over)\b|\bparked\b")),
    ("observation", re.compile(r"\bobserv|\bspotted\b|\bnoticed\b|\bsaw\b")),
]


def event_of(text: str) -> Optional[str]:
    t = text.lower().replace("_", " ")
    for name, rx in EVENTS:
        if rx.search(t):
            return name
    return None
