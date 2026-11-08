import json
import unittest

from model_client import ModelError
from pipeline import analyze_document


TEXT = "1. Цели обработки\nДанные используются для регистрации.\n\nДля поддержки используется та же электронная почта.\n\n2. Срок хранения\nДанные удаляются после закрытия аккаунта."


def prompt_blocks(prompt):
    return json.loads(prompt.split('<document_blocks>\n')[1].split('\n</document_blocks>')[0])


def risk_answer(prompt):
    blocks = prompt_blocks(prompt)
    return {"blocks": [{"id": b["id"], "title": "Проверенный раздел", "summary": "Описание"} for b in blocks], "risks": []}, {"served_by": "offline-fixture", "latency_s": 0}


class SemanticTests(unittest.TestCase):
    def test_segmentation_progress_is_visible_before_risk_analysis(self):
        events=[]
        def client(prompt,schema,**kwargs):
            if 'groups' in schema['properties']:
                spans=prompt_blocks(prompt)
                return {'groups':[{'first_id':spans[0]['id'],'last_id':spans[-1]['id'],'title':'Раздел'}]},{'latency_s':0}
            self.assertIn(('segmentation',1,1),events)
            return risk_answer(prompt)
        analyze_document(TEXT,client=client,stage_progress=lambda stage,done,total:events.append((stage,done,total)))
        self.assertIn(('risk_analysis',1,1),events)

    def test_different_topics_inside_one_paragraph_can_be_separated(self):
        text = 'Данные используются только для регистрации. Хранение прекращается после закрытия аккаунта.'
        def client(prompt, schema, **kwargs):
            if "groups" in schema["properties"]:
                spans = prompt_blocks(prompt)
                return {"groups": [{"first_id": b["id"], "last_id": b["id"], "title": "Отдельная тема"} for b in spans]}, {"latency_s": 0}
            return risk_answer(prompt)
        result = analyze_document(text, client=client)
        self.assertEqual([b['text'] for b in result['blocks']], ['Данные используются только для регистрации.', 'Хранение прекращается после закрытия аккаунта.'])

    # Would catch dropping the segmentation stage or reconstructing text from LLM prose.
    def test_same_topic_paragraphs_merge_with_exact_source_text(self):
        def client(prompt, schema, **kwargs):
            if "groups" in schema["properties"]:
                return {"groups": [
                    {"first_id": "b001", "last_id": "b002", "title": "Цели обработки"},
                    {"first_id": "b003", "last_id": "b003", "title": "Срок хранения"}
                ]}, {"served_by": "offline-fixture", "latency_s": 0}
            return risk_answer(prompt)
        result = analyze_document(TEXT, client=client)
        self.assertEqual(len(result["blocks"]), 2)
        self.assertEqual(result["blocks"][0]["text"], "1. Цели обработки\nДанные используются для регистрации.\n\nДля поддержки используется та же электронная почта.")
        self.assertEqual(result["blocks"][0]["source_ids"], ["b001", "b002"])
        self.assertEqual(result["blocks"][0]["semantic_title"], "Цели обработки")
        self.assertEqual(len(result["calls"]), 2)
        for block in result["blocks"]:
            self.assertEqual(TEXT[block["start"]:block["end"]], block["text"])

    # Would catch accepting missing, duplicated, reordered or invented source spans.
    def test_invalid_group_partitions_are_rejected(self):
        invalid = [
            [("b002", "b003")],
            [("b001", "b002"), ("b002", "b003")],
            [("b002", "b001"), ("b002", "b003")],
            [("b001", "b999")],
            []
        ]
        for ranges in invalid:
            with self.subTest(ranges=ranges):
                def client(prompt, schema, **kwargs):
                    if "groups" in schema["properties"]:
                        return {"groups": [{"first_id": a, "last_id": b, "title": "Раздел"} for a,b in ranges]}, {"latency_s": 0}
                    return risk_answer(prompt)
                with self.assertRaises(ModelError):
                    analyze_document(TEXT, client=client)

    def test_segmentation_failure_is_not_silently_reported_as_semantic_success(self):
        def client(prompt, schema, **kwargs):
            if "groups" in schema["properties"]:
                raise ModelError("Модель недоступна")
            return risk_answer(prompt)
        with self.assertRaises(ModelError):
            analyze_document(TEXT, client=client)


if __name__ == '__main__': unittest.main()
