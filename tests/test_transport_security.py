import io
import json
import unittest
import urllib.error
import urllib.request
from unittest.mock import patch
import llm_layer


class TransportSecurityTests(unittest.TestCase):
    def test_authenticated_redirects_do_not_forward_headers(self):
        handler=getattr(llm_layer,'NoCredentialRedirect',urllib.request.HTTPRedirectHandler)()
        req=urllib.request.Request('https://provider.invalid/api',data=b'{}',headers={'Authorization':'synthetic','x-goog-api-key':'synthetic'})
        for url in ('https://other.invalid/api','http://provider.invalid/api','https://provider.invalid/other'):
            with self.subTest(url=url):
                redirected=handler.redirect_request(req,None,302,'',{},url)
                self.assertIsNone(redirected)

    @patch.dict('os.environ',{'GEMINI_API_KEY':'synthetic'})
    @patch('urllib.request.OpenerDirector.open',side_effect=urllib.error.HTTPError('https://provider.invalid',400,'bad',{},io.BytesIO(b'secret-marker')))
    def test_legacy_errors_do_not_echo_remote_secrets(self, opened):
        with self.assertLogs('llm',level='ERROR') as logs:
            result=llm_layer.generate('public fixture',retries=0)
        self.assertFalse(result['ok'])
        self.assertNotIn('secret-marker',result['error'])
        self.assertNotIn('secret-marker',''.join(logs.output))

    @patch.dict('os.environ',{'GEMINI_API_KEY':'synthetic'})
    @patch('urllib.request.OpenerDirector.open')
    def test_legacy_truncation_is_not_success(self, opened):
        opened.return_value=io.BytesIO(json.dumps({'candidates':[{'finishReason':'MAX_TOKENS','content':{'parts':[{'text':'partial'}]}}]}).encode())
        result=llm_layer.generate('public fixture',retries=0)
        self.assertFalse(result['ok'])


if __name__=='__main__':unittest.main()
