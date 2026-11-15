import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

import numpy as np

try:
    from visual_fidelity import qa_timeline
except ModuleNotFoundError:
    import qa_timeline


class TimelineTest(unittest.TestCase):
    def test_cut_peak_reports_one_frame_of_drift(self):
        timeline={
            "frames":8,"fps":24,
            "shots":[{"id":"a","start":0,"end":4},{"id":"b","start":4,"end":8}],
        }
        frames=np.zeros((8,3,3,3),np.uint8)
        source=(24,np.array([0,1,2,3,22,1,1,1]),frames)
        render=(24,np.array([0,1,2,3,1,21,1,1]),frames)
        with tempfile.TemporaryDirectory() as folder:
            dest=Path(folder)/"report.csv"
            with patch.object(qa_timeline,"get_series",side_effect=[source,render]):
                report=qa_timeline.summarize(Path("ref"),Path("out"),timeline,dest)
            self.assertEqual(report["shots"][1]["peak_shift_frames"],1)
            self.assertEqual(len(dest.read_text().splitlines()),9)

    def test_rejects_incompatible_duration(self):
        timeline={"frames":2,"fps":24,"shots":[{"id":"a","start":0,"end":2}]}
        source=(24,np.zeros(2),np.zeros((2,2,2,3),np.uint8))
        render=(24,np.zeros(1),np.zeros((1,2,2,3),np.uint8))
        with patch.object(qa_timeline,"get_series",side_effect=[source,render]):
            with self.assertRaisesRegex(ValueError,"incompatíveis"):
                qa_timeline.summarize(Path("ref"),Path("out"),timeline,Path("unused.csv"))
