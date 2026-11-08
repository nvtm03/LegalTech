import unittest
import evaluate


class EndToEndMetricTests(unittest.TestCase):
    def test_correct_category_in_wrong_location_is_not_a_hit(self):
        case={'target_category':'retention','expected_target_present':True,'target_start':100,'target_end':150,'reference_starts':[0,100,200]}
        result={'blocks':[{'start':0},{'start':100},{'start':250}],'risks':[{'category':'retention','quote_start':0,'quote_end':30}]}
        score=getattr(evaluate,'score_end_to_end',lambda *a:{ })(case,result)
        self.assertIs(score.get('target_found'),False)
        self.assertIs(score.get('matches_expected'),False)
        self.assertEqual(score.get('mislocalized'),1)
        self.assertEqual(score.get('boundary_tp'),1)
        self.assertEqual(score.get('boundary_fp'),1)
        self.assertEqual(score.get('boundary_fn'),1)

    def test_valid_localized_evidence_counts_but_missing_answer_does_not(self):
        case={'target_category':'retention','expected_target_present':True,'target_start':100,'target_end':150,'reference_starts':[0,100]}
        result={'blocks':[{'start':0},{'start':100}],'risks':[{'category':'retention','quote_start':120,'quote_end':140}]}
        score=getattr(evaluate,'score_end_to_end',lambda *a:{ })(case,result)
        self.assertIs(score.get('matches_expected'),True)
        case['expected_target_present']=False
        missing=getattr(evaluate,'score_end_to_end',lambda *a:{ })(case,None)
        self.assertIs(missing.get('matches_expected'),False)
        self.assertIs(missing.get('ok'),False)


if __name__=='__main__':unittest.main()

class OutcomeTests(unittest.TestCase):
    def test_control_with_wrong_location_finding_is_not_clean(self):
        case={'target_category':'retention','expected_target_present':False,'target_start':100,'target_end':150}
        result={'blocks':[{'start':0}],'risks':[{'category':'retention','quote_start':0,'quote_end':30}]}
        scored=evaluate.score_end_to_end(case,result)
        self.assertFalse(scored['matches_expected'])
        self.assertEqual(scored.get('outcome'),'mislocalized')

    def test_technical_error_is_separate_from_valid_model_miss(self):
        case={'target_category':'retention','expected_target_present':True,'target_start':100,'target_end':150}
        failed=evaluate.score_end_to_end(case,None)
        missed=evaluate.score_end_to_end(case,{'blocks':[{'start':0}],'risks':[]})
        self.assertEqual(failed.get('outcome'),'technical_error')
        self.assertEqual(missed.get('outcome'),'miss')

class SummaryTests(unittest.TestCase):
    def test_historical_clean_label_with_mislocalized_finding_is_not_counted_correct(self):
        from evaluate_e2e import summarize
        summary=summarize([{'model':'fixture','segmentation':'semantic','ok':True,'expected_target_present':False,
            'target_found':False,'matches_expected':True,'mislocalized':1}])['fixture/semantic']
        self.assertEqual(summary['localized_correct'],0)
        self.assertEqual(summary['flagged_controls'],1)
