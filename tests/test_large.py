import json
import time
import unittest
from helpers import findings


class Large(unittest.TestCase):
    def test_250k_camera_rows_and_20k_notes_run_in_reasonable_time(self):
        cam = ["#PLEARUN big", "timestamp,device,speed_mph,zone_mph"]
        for i in range(250000):
            cam.append(f"{1772500000000 + i * 1000},CAM-{i % 5:02d},{30 + i % 40},45")
        notes = ["ID,Author,Note,Time"] + [f"N-{i},Lee,\"note {i}, text\",21:{i % 60:02d}" for i in range(20000)]
        events = [{"id": f"D-{i}", "type": "unit_on_scene", "logged": "2026-03-02T21:17:19-05:00", "unit": f"L-{i}"}
                  for i in range(5000)]
        t0 = time.time()
        f = findings("Incident 2026-03-02.\nHe was travelling 58 mph at about 21:14.\nA unit was on scene at 21:17.\n",
                     {"camera_log.csv": "\n".join(cam) + "\n", "notes.csv": "\n".join(notes) + "\n",
                      "dispatch.json": json.dumps({"events": events})})
        elapsed = time.time() - t0
        self.assertEqual(len(f), 2)
        self.assertLess(elapsed, 60, f"took {elapsed:.1f}s")


if __name__ == "__main__":
    unittest.main()
