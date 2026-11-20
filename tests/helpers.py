import os, sys, tempfile, json
ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if ROOT not in sys.path:
    sys.path.insert(0, ROOT)
from vf.pipeline import run


def make_case(report, files):
    """files: {name: str|bytes}. Returns (report_path, records_dir, tmpdir)."""
    d = tempfile.mkdtemp()
    rec = os.path.join(d, "records")
    os.makedirs(rec)
    for name, content in files.items():
        with open(os.path.join(rec, name), "wb") as fh:
            fh.write(content if isinstance(content, bytes) else content.encode("utf-8"))
    rp = os.path.join(d, "report.txt")
    with open(rp, "w", encoding="utf-8") as fh:
        fh.write(report)
    return rp, rec, d


def findings(report, files):
    rp, rec, _ = make_case(report, files)
    return run(rp, rec)["findings"]
