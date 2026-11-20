import unittest
from helpers import ROOT, make_case
import os
from vf.loaders import load_dir, load_csv, load_json, load_vtt, decode


class Loaders(unittest.TestCase):
    def setUp(self):
        self.rows, self.warn = load_dir(os.path.join(ROOT, "records"))
        self.by = {}
        for r in self.rows:
            self.by.setdefault(r.file, []).append(r)

    def test_no_warnings_and_all_files(self):
        self.assertEqual(self.warn, [])
        self.assertEqual(set(self.by), {"camera_log.csv", "dispatch.json", "notes_cp1252.csv", "bodycam_transcript.vtt"})

    def test_csv_rows_are_one_based_and_skip_marker_and_header(self):
        cam = self.by["camera_log.csv"]
        self.assertEqual(cam[0].row, 1)
        self.assertEqual(cam[0].raw, "1772502579000,CAM-07,42,45")      # first DATA line, not the marker/header
        self.assertEqual([r.row for r in cam], list(range(1, len(cam) + 1)))

    def test_vtt_cue_numbers_one_based(self):
        self.assertEqual([r.row for r in self.by["bodycam_transcript.vtt"]], [1, 2, 3])

    def test_json_rows_in_document_order(self):
        self.assertEqual([r.fields["id"] for r in self.by["dispatch.json"]], ["D-1001", "D-1002", "D-1003"])
        for r in self.by["dispatch.json"]:                              # raw is the exact file span
            self.assertIn(r.fields["logged"] if isinstance(r.fields["logged"], str) else str(r.fields["logged"]), r.raw)

    def test_cp1252_smart_quotes(self):
        data = 'ID,Author,Note,Time\r\nN-1,Lee,"He said \u201chi\u201d at the caf\u00e9",21:15\r\n'.encode("cp1252")
        rows = load_csv("n.csv", decode(data))
        self.assertIn("\u201chi\u201d", rows[0].text)
        self.assertIn("caf\u00e9", rows[0].raw)

    def test_bom_marker_and_mixed_line_endings(self):
        txt = "\ufeff#PLEARUN x\ntimestamp,device,speed_mph,zone_mph\r\n1772502579000,C1,42,45\r\n\r\n1772502580000,C1,50,45\n"
        rows = load_csv("c.csv", decode(txt.encode("utf-8")))
        self.assertEqual([(r.row, r.speed_mph) for r in rows], [(1, 42.0), (2, 50.0)])

    def test_malformed_row_kept_for_numbering_but_unusable(self):
        txt = "timestamp,device,speed_mph,zone_mph\n1772502579000,C1,42,45\nnot-a-time,C1,50,45\n1772502581000,C1,51,45\n"
        rows = load_csv("c.csv", txt)
        self.assertEqual([r.row for r in rows], [1, 2, 3])
        self.assertTrue(rows[1].malformed)

    def test_multiline_quoted_field_raw_spans_lines(self):
        txt = 'ID,Author,Note,Time\nN-1,Lee,"line one\nline two",21:15\nN-2,Lee,ok,21:16\n'
        rows = load_csv("n.csv", txt)
        self.assertEqual(len(rows), 2)
        self.assertIn("line one\nline two", rows[0].raw)

    def test_vtt_overlap_and_notes(self):
        txt = "WEBVTT\n\nNOTE hi\n\n1\n00:00:00.000 --> 00:00:04.000\nA\n\n00:00:03.000 --> 00:00:05.000\nB\n"
        rows = load_vtt("v.vtt", txt)
        self.assertEqual([(r.row, r.raw) for r in rows], [(1, "A"), (2, "B")])

    def test_deeply_nested_json_falls_back(self):
        txt = "[" * 5000 + "]" * 5000
        self.assertEqual(load_json("d.json", txt), [])


if __name__ == "__main__":
    unittest.main()
