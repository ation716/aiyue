import csv
import json
import tempfile
import unittest
from pathlib import Path

from backtest.result_store import save_result_files


ROOT = Path(__file__).resolve().parents[1]
REAL_RESULT = ROOT / "results" / "daily" / "E05" / "20260928_111656_101066"


class TestResultStore(unittest.TestCase):
    def test_save_csv_json_and_chart_from_real_result(self):
        result = {
            "trades": json.loads((REAL_RESULT / "trades.json").read_text(encoding="utf-8")),
            "equity": json.loads((REAL_RESULT / "equity.json").read_text(encoding="utf-8")),
            "final": json.loads((REAL_RESULT / "final.json").read_text(encoding="utf-8")),
        }
        with tempfile.TemporaryDirectory() as temp:
            paths = save_result_files(result, temp)
            for path in paths.values():
                self.assertTrue(Path(path).exists())
            with Path(paths["trades_csv"]).open(encoding="utf-8-sig", newline="") as handle:
                rows = list(csv.DictReader(handle))
            self.assertEqual(len(rows), len(result["trades"]))
            self.assertEqual(
                json.loads(Path(paths["final_json"]).read_text(encoding="utf-8"))["total"],
                result["final"]["total"],
            )
            self.assertGreater(Path(paths["equity_chart"]).stat().st_size, 0)


if __name__ == "__main__":
    unittest.main()
