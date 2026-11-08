import hashlib
import io
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch
import collect_corpus

TEXT=('Политика персональных данных. '+('Пользователь получает описание обработки. '*25)).rstrip()
CONTENT=("<html><head><meta charset='utf-8'></head><main>"+TEXT+'</main></html>').encode()


class Response(io.BytesIO):
    headers={'Content-Type':'text/html'}
    url='https://example.invalid/policy'


class CollectorTests(unittest.TestCase):
    def prepare(self,root):
        source={'id':'fixture','url':Response.url,'format':'html','company':'Fixture','doc_type':'privacy'}
        old={**source,'status':'downloaded','sha256':hashlib.sha256(CONTENT).hexdigest(),'text_sha256':hashlib.sha256(TEXT.encode()).hexdigest()}
        (root/'sources.json').write_text(json.dumps([source]))
        (root/'manifest.json').write_text(json.dumps([old]))
        return old

    def test_missing_or_corrupted_snapshots_are_restored_from_pinned_source(self):
        for corrupted in (False,True):
            with self.subTest(corrupted=corrupted), tempfile.TemporaryDirectory() as directory:
                root=Path(directory);self.prepare(root)
                if corrupted:
                    (root/'raw').mkdir();(root/'raw/fixture.html').write_bytes(b'corrupt')
                with patch.object(collect_corpus,'ROOT',root),patch('urllib.request.urlopen',side_effect=lambda *a,**k:Response(CONTENT)):
                    records=collect_corpus.collect()
                self.assertTrue((root/'raw/fixture.html').exists())
                self.assertEqual((root/'raw/fixture.html').read_bytes(),CONTENT)
                self.assertEqual((root/'raw/fixture.txt').read_text(),TEXT)
                self.assertEqual(len(records),1)

    def test_changed_remote_version_does_not_replace_pinned_snapshot(self):
        with tempfile.TemporaryDirectory() as directory:
            root=Path(directory);old=self.prepare(root)
            with patch.object(collect_corpus,'ROOT',root),patch('urllib.request.urlopen',side_effect=lambda *a,**k:Response(CONTENT.replace(b'</main>',b' changed</main>'))):
                rows=collect_corpus.collect()
            self.assertEqual(rows[0]['status'],'version_changed')
            self.assertEqual(rows[0]['sha256'],old['sha256'])
            self.assertFalse((root/'raw/fixture.html').exists())
            self.assertTrue(list((root/'raw/versions').rglob('*.html')))


if __name__=='__main__':unittest.main()

class PageMapTests(unittest.TestCase):
    def test_pdf_coordinates_select_exact_original_page_text(self):
        from types import SimpleNamespace
        pages=[SimpleNamespace(extract_text=lambda:'Первая страница'),SimpleNamespace(extract_text=lambda:'Вторая страница')]
        with patch('collect_corpus.PdfReader',return_value=SimpleNamespace(pages=pages)):
            helper=getattr(collect_corpus,'extract_pdf_snapshot',lambda data:('',[]))
            text,mapping=helper(b'fixture')
        self.assertEqual(text,'Первая страница\n\nВторая страница')
        self.assertEqual(mapping[1],{'page':2,'start':17,'end':32})
        self.assertEqual(text[mapping[1]['start']:mapping[1]['end']],'Вторая страница')
