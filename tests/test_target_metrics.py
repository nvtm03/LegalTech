import unittest
import evaluate


class TargetMetricsTests(unittest.TestCase):
    # Would catch counting missing responses as clean documents or treating unlabelled categories as false positives.
    def test_errors_are_not_true_negatives_and_off_target_findings_are_not_scored(self):
        rows = [
            {"ok": True, "expected_target_present": False, "target_category":"retention", "predicted":["other"]},
            {"ok": True, "expected_target_present": True, "target_category":"retention", "predicted":["retention"]},
            {"ok": True, "expected_target_present": False, "target_category":"retention", "predicted":["retention"]},
            {"ok": False, "expected_target_present": False, "target_category":"retention", "predicted":[]}
        ]
        summarize = getattr(evaluate, 'summarize_target_records', lambda records: {})
        result = summarize(rows)
        self.assertEqual(result.get('tp'), 1)
        self.assertEqual(result.get('tn'), 1)
        self.assertEqual(result.get('fp'), 1)
        self.assertEqual(result.get('fn'), 0)
        self.assertEqual(result.get('errors'), 1)
        self.assertEqual(result.get('correct_over_all_cases'), .5)


if __name__ == '__main__': unittest.main()
