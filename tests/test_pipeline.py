import copy
import unittest
from unittest.mock import patch

from model_client import ModelError, generate_json
from pipeline import analyze_document, split_blocks, validate_answer
from evaluate import score


def good_answer(blocks):
    return {"blocks": [{"id": b["id"], "title": "Условие", "summary": "Краткое описание"} for b in blocks], "risks": []}


class PipelineTests(unittest.TestCase):
    def test_offsets_and_lossless_nonwhitespace_coverage(self):
        text = "  1. Первый пункт.\n\n2. Второй пункт.\n2.1 Дополнение. " + "Слово " * 1000
        blocks = split_blocks(text)
        self.assertTrue(all(b["text"] == text[b["start"]:b["end"]] for b in blocks))
        self.assertTrue(all(len(b["text"]) <= 3500 for b in blocks))
        self.assertEqual("".join(text.split()), "".join("".join(b["text"].split()) for b in blocks))

    def test_long_word_never_stalls(self):
        blocks = split_blocks("я" * 10000)
        self.assertEqual(sum(len(b["text"]) for b in blocks), 10000)

    def test_empty_and_oversized_rejected(self):
        for value in ("   ", "x" * 120001):
            with self.assertRaises(ValueError): split_blocks(value)

    def test_invented_quote_is_rejected(self):
        blocks = split_blocks("Реальная формулировка документа")
        answer = good_answer(blocks)
        answer["risks"] = [{"block_id": "b001", "category": "other", "severity": "high", "quote": "Несуществующая цитата", "reason": "Причина", "suggestion": "Совет", "related_block_ids": []}]
        with self.assertRaises(ModelError): validate_answer(answer, blocks)
        answer["risks"][0]["quote"] = "Реальная формулировка"
        validate_answer(answer, blocks)
        answer["risks"][0]["related_block_ids"] = ["b999"]
        with self.assertRaises(ModelError): validate_answer(answer, blocks)

    def test_missing_duplicate_and_unknown_blocks_rejected(self):
        blocks = split_blocks("Первый блок\n\nВторой блок")
        answer = good_answer(blocks)
        for ids in ([], ["b001", "b001"], ["b001", "b999"]):
            bad = copy.deepcopy(answer)
            bad["blocks"] = [{"id": i, "title": "a", "summary": "b"} for i in ids]
            with self.assertRaises(ModelError): validate_answer(bad, blocks)

    def test_schema_rejects_unknown_risk_category(self):
        blocks = split_blocks("Содержание документа")
        answer = good_answer(blocks)
        answer["risks"] = [{"block_id":"b001", "category":"invented", "severity":"high", "quote":"Содержание", "reason":"r", "suggestion":"s", "related_block_ids":[]}]
        with self.assertRaises(ModelError): validate_answer(answer, blocks)

    def test_batching_preserves_all_blocks_and_metadata(self):
        text = ("Содержательный абзац. " * 140 + "\n\n") * 10
        calls = []
        def fake(prompt, schema, **kwargs):
            import json
            blocks = json.loads(prompt.split('<document_blocks>\n')[1].split('\n</document_blocks>')[0])
            calls.append(blocks)
            return good_answer(blocks), {"model":"fake", "served_by":"fake", "latency_s":0}
        result = analyze_document(text, client=fake, segmentation="paragraphs")
        self.assertGreater(len(calls), 1)
        self.assertEqual([b["id"] for b in result["blocks"]], [b["id"] for b in split_blocks(text)])

    def test_evaluation_counts_false_positives(self):
        self.assertEqual(score(["retention"], ["retention", "other"]), {"tp":1,"fp":1,"fn":0})


class RouterTests(unittest.TestCase):
    @patch.dict('os.environ',{'ROUTER_API_KEY':'test-key'})
    @patch('model_client.time.sleep')
    @patch('model_client._request')
    def test_resume_observes_existing_remote_job_instead_of_submitting_again(self, request, sleep):
        state={}
        def checkpoint(key,value=None):
            if value is not None:state[key]=value
            return state.get(key)
        request.side_effect=[{'id':'job_saved','status':'queued'},
                             {'id':'job_saved','status':'done','result':{'text':'{"ok":true}','finishReason':'STOP'}}]
        with self.assertRaises(ModelError):
            generate_json('fixture',{'type':'object'},provider='router',timeout=1,checkpoint=checkpoint)
        answer,meta=generate_json('fixture',{'type':'object'},provider='router',timeout=60,checkpoint=checkpoint)
        self.assertTrue(answer['ok'])
        self.assertEqual(meta['job_id'],'job_saved')
        self.assertEqual(sum(len(call.args)>2 for call in request.call_args_list),1)
        again,_=generate_json('fixture',{'type':'object'},provider='router',checkpoint=checkpoint)
        self.assertTrue(again['ok'])
        self.assertEqual(request.call_count,2)

    @patch.dict("os.environ", {"ROUTER_API_KEY":"test-key"})
    @patch("model_client.time.sleep")
    @patch("model_client._request")
    def test_polling_and_explicit_model(self, request, sleep):
        request.side_effect = [{"id":"job_123", "status":"queued"}, {"id":"job_123", "status":"done", "result":{"text":'{"ok":true}', "finishReason":"STOP"}}]
        answer, meta = generate_json("test", {"type":"object"}, provider="router", model="test-model")
        self.assertTrue(answer["ok"])
        self.assertFalse(request.call_args_list[0].args[2]["fallback"])
        self.assertEqual(meta["job_id"], "job_123")
        sleep.assert_called_once_with(10)

    @patch.dict("os.environ", {"ROUTER_API_KEY":"test-key"})
    @patch("model_client._request", return_value={"id":"job_a", "status":"queued"})
    def test_deadline_does_not_resubmit(self, request):
        with self.assertRaises(ModelError): generate_json("test", {}, provider="router", timeout=1)
        self.assertEqual(request.call_count, 1)

    @patch.dict("os.environ", {"ROUTER_API_KEY":"test-key"})
    @patch("model_client._request", return_value={"id":"job_a", "status":"done", "result":{"text":"{}", "finishReason":"MAX_TOKENS"}})
    def test_truncated_response_rejected(self, request):
        with self.assertRaises(ModelError): generate_json("test", {}, provider="router")


if __name__ == '__main__': unittest.main()
