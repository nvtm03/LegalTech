import json
import unittest
from pipeline import locate_evidence, analyze_document, _batches
from model_client import ModelError


class AuditRegressions(unittest.TestCase):
    def test_amount_boundaries_and_negation_cannot_be_stripped(self):
        for source, quote in [('Пени 0,5 процента в день', '5 процента'),
                              ('Стоимость 100 000 рублей', '000 рублей'),
                              ('Передача данных не разрешена.', 'разрешена.')]:
            with self.subTest(source=source), self.assertRaises(ModelError):
                locate_evidence({'text': source, 'start': 0}, quote)

    def test_evidence_includes_original_sentence_context(self):
        evidence = locate_evidence({'text':'Первое условие. Хранение данных бессрочно. Последнее условие.', 'start':100}, 'бессрочно')
        self.assertEqual(evidence.get('context'), 'Хранение данных бессрочно.')
        self.assertEqual(evidence.get('context_start'),116)

    def client(self, prompt, schema, **kwargs):
        if 'relations' in schema['properties']:
            raise ModelError('Сервис проверки связей недоступен')
        blocks=json.loads(prompt.split('<document_blocks>\n')[1].split('\n</document_blocks>')[0])
        return {'blocks':[{'id':b['id'],'title':'Условия','summary':'Условия сервиса'} for b in blocks], 'risks':[]},{}

    def test_relation_failure_preserves_verified_risk_results(self):
        result=analyze_document('Условия хранения данных установлены в документе.',segmentation='paragraphs',client=self.client,check_relations=True)
        self.assertEqual(len(result['blocks']),1)
        self.assertEqual(result['relation_review']['status'],'failed')
        self.assertTrue(result.get('partial'))

    def test_batch_budget_counts_metadata_and_limits_items(self):
        blocks=[{'id':str(i),'start':i*4,'end':i*4+2,'text':'Да'} for i in range(500)]
        batches=list(_batches(blocks))
        self.assertGreater(len(batches),1)
        for batch in batches:
            self.assertLessEqual(len(json.dumps(batch,ensure_ascii=False)),11000)
            self.assertLessEqual(len(batch),60)

    def test_unrelated_exception_does_not_qualify_retention_risk(self):
        text='Хранение бессрочно. Обращение подаётся лично.\n\nИсключение: обращение можно подать по email.'
        def client(prompt,schema,**kwargs):
            if 'relations' in schema['properties']:
                return {'relations':[{'left_id':'b001','right_id':'b002','kind':'exception','left_quote':'Обращение подаётся лично.',
                    'right_quote':'Исключение: обращение можно подать по email.','explanation':'Способ обращения уточнён.'}]},{}
            blocks=json.loads(prompt.split('<document_blocks>\n')[1].split('\n</document_blocks>')[0])
            return {'blocks':[{'id':b['id'],'title':'Условия','summary':'Условия'} for b in blocks],
                    'risks':[{'block_id':'b001','category':'retention','severity':'high','quote':'Хранение бессрочно.',
                    'reason':'Срок не ограничен','suggestion':'Уточнить срок','related_block_ids':[]}]},{}
        result=analyze_document(text,segmentation='paragraphs',client=client,check_relations=True)
        self.assertNotEqual(result['risks'][0].get('context_status'),'review_with_related_clause')

class BudgetAndRecoveryTests(unittest.TestCase):
    def test_gemma_rejects_overbudget_payload_before_network_call(self):
        from unittest.mock import patch
        from model_client import generate_json
        with patch.dict('os.environ',{'ROUTER_API_KEY':'synthetic'}),patch('model_client._request') as remote:
            with self.assertRaises(ModelError):
                generate_json('я'*20000,{'type':'object'},provider='router',model='gemma-4-26b-a4b-it')
            remote.assert_not_called()

    def test_long_document_with_no_selected_pairs_is_not_completed(self):
        def client(prompt,schema,**kwargs):
            if 'pairs' in schema['properties']:return {'pairs':[]},{}
            return AuditRegressions().client(prompt,schema,**kwargs)
        result=analyze_document(('Условия использования сервиса описаны ниже.\n\n'*400),segmentation='paragraphs',client=client,check_relations=True)
        self.assertEqual(result['relation_review']['status'],'no_candidates')
