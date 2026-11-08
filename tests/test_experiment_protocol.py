import json
import subprocess
import tempfile
import unittest
from pathlib import Path

class ProtocolTests(unittest.TestCase):
    def test_family_overlap_is_rejected_even_with_optimized_python(self):
        code="from prepare_e2e_cases import validate_families; validate_families([{'family_id':'same'}],[{'family_id':'same'}])"
        result=subprocess.run(['.venv/bin/python','-O','-c',code],capture_output=True,text=True)
        self.assertNotEqual(result.returncode,0)
        self.assertIn('Source family leakage',result.stderr)

    def test_offline_summary_separates_timeout_from_missed_injection(self):
        with tempfile.TemporaryDirectory() as directory:
            source=Path(directory)/'records.json'; target=Path(directory)/'summary.json'
            source.write_text(json.dumps({'records':[
                {'model':'fixture','segmentation':'semantic','ok':False,'expected_target_present':True,'target_found':False,'matches_expected':False,'mislocalized':0},
                {'model':'fixture','segmentation':'semantic','ok':True,'expected_target_present':True,'target_found':False,'matches_expected':False,'mislocalized':0}]}))
            process=subprocess.run(['.venv/bin/python','evaluate_e2e.py','--summarize',str(source),'--output',str(target)],capture_output=True,text=True)
            self.assertEqual(process.returncode,0,process.stderr)
            summary=json.loads(target.read_text())['summary']['fixture/semantic']
            self.assertEqual(summary['technical_errors'],1)
            self.assertEqual(summary['missed_injections'],1)
            self.assertEqual(summary['cases'],2)
