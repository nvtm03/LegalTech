import hashlib
import json
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest

SCRIPT = Path(__file__).resolve().parents[1] / 'build_benchmark.py'


class BenchmarkTests(unittest.TestCase):
    # Would catch mutating raw snapshots, using the wrong excerpt, or separating a pair.
    def test_pair_has_exact_source_and_only_declared_replacement(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            original = 'Введение.\nДанные хранятся один год.\nОбращения принимаются по почте.'
            (root/'source.txt').write_text(original)
            spec = {'id':'case1','source_id':'source','doc_type':'privacy','family_id':'company1','split':'development',
                    'source_text_sha256':hashlib.sha256(original.encode()).hexdigest(),'start':10,'end':35,
                    'replace':'один год','replacement':'бессрочно','target_category':'retention'}
            # Literal offsets independently checked against the source fixture.
            (root/'specs.json').write_text(json.dumps([spec]))
            run = subprocess.run([sys.executable,str(SCRIPT),'--source-dir',str(root),'--specs',str(root/'specs.json'),'--output',str(root/'cases.json')],capture_output=True,text=True)
            self.assertEqual(run.returncode, 0, run.stderr)
            control, mutation = json.loads((root/'cases.json').read_text())
            self.assertEqual(control['text'], 'Данные хранятся один год.')
            self.assertEqual(mutation['text'], 'Данные хранятся бессрочно.')
            self.assertFalse(control['expected_target_present'])
            self.assertTrue(mutation['expected_target_present'])
            self.assertEqual(control['family_id'], mutation['family_id'])
            self.assertEqual(control['split'], mutation['split'])
            self.assertEqual((root/'source.txt').read_text(), original)

    # Would catch unnoticed source drift and fabrication of a matching excerpt.
    def test_changed_snapshot_is_rejected_without_writing_cases(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            (root/'source.txt').write_text('Изменённый документ')
            spec={'id':'case1','source_id':'source','doc_type':'privacy','family_id':'company1','split':'development',
                  'source_text_sha256':'0'*64,'start':0,'end':18,'replace':'документ','replacement':'текст','target_category':'retention'}
            (root/'specs.json').write_text(json.dumps([spec]))
            run=subprocess.run([sys.executable,str(SCRIPT),'--source-dir',str(root),'--specs',str(root/'specs.json'),'--output',str(root/'cases.json')],capture_output=True,text=True)
            self.assertEqual(run.returncode,1)
            self.assertIn('SHA-256',run.stderr)
            self.assertFalse((root/'cases.json').exists())


if __name__ == '__main__': unittest.main()
