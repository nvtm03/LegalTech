import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch
import generate_report


class ReportTests(unittest.TestCase):
    # Would catch silently omitting new measured results or changing their denominator.
    def test_real_fragment_pilot_is_rendered_with_its_own_denominator(self):
        with tempfile.TemporaryDirectory() as directory:
            root=Path(directory)
            (root/'results').mkdir()
            (root/'data/corpus').mkdir(parents=True)
            base={'model':'fixture','records':[],'summary':{}}
            (root/'results/prompt_comparison.json').write_text(json.dumps(base))
            (root/'data/corpus/manifest.json').write_text('[]')
            pilot={'model':'fixture','records':[],'summary':{'checklist':{'cases':6,'tp':3,'tn':3,'fp':0,'fn':0,'errors':0,'correct_over_all_cases':1}}}
            (root/'results/real-derived-pilot-v1.json').write_text(json.dumps(pilot))
            with patch.object(generate_report,'ROOT',root):
                generate_report.render()
            html=(root/'reports/stage2-draft.html').read_text()
            self.assertIn('Проверка на реальных фрагментах',html)
            self.assertIn('6/6',html)
            self.assertIn('Не оценка всего документа',html)


if __name__=='__main__': unittest.main()
