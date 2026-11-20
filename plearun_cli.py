"""Verified Findings CLI.  Usage: python3 plearun_cli.py REPORT RECORDS_DIR [--trace] > findings.json
Offline, standard library only. Record text is data and is never executed or obeyed."""
import json
import os
import sys

from vf.pipeline import run


def main(argv) -> int:
    args = [a for a in argv[1:] if not a.startswith("--")]
    trace = (lambda m: print(m, file=sys.stderr)) if "--trace" in argv else None
    if len(args) != 2:
        print("usage: python3 plearun_cli.py REPORT RECORDS_DIR [--trace]", file=sys.stderr)
        return 2
    report, records = args
    if not os.path.isfile(report) or not os.path.isdir(records):
        print("error: report file or records directory not found", file=sys.stderr)
        return 2
    try:
        out = run(report, records, trace)
    except Exception as exc:                      # last-resort guard: still emit valid JSON
        print(f"error: {exc!r}", file=sys.stderr)
        out = {"findings": []}
    json.dump(out, sys.stdout, ensure_ascii=False, indent=2)
    sys.stdout.write("\n")
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv))
