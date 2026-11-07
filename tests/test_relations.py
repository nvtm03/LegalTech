import json
import unittest
from pipeline import analyze_document
from model_client import ModelError

LEFT='Компания полностью освобождается от ответственности за задержку.'
RIGHT='Исключение: за задержку свыше пяти дней компания возмещает документально подтверждённый ущерб.'
TEXT=LEFT+'\n\n'+('Описание технического порядка использования сервиса. '*250)+'\n\n'+RIGHT


class RelationTests(unittest.TestCase):
    def test_two_distinct_clauses_inside_one_semantic_block_can_be_related(self):
        text=LEFT+'\n'+RIGHT
        def client(prompt,schema,**kwargs):
            if 'groups' in schema['properties']:
                spans=json.loads(prompt.split('<document_blocks>\n')[1].split('\n</document_blocks>')[0])
                return {'groups':[{'first_id':spans[0]['id'],'last_id':spans[-1]['id'],'title':'Ответственность и исключение'}]},{'latency_s':0}
            if 'relations' in schema['properties']:
                return {'relations':[{'left_id':'b001','right_id':'b001','kind':'exception','left_quote':LEFT,'right_quote':RIGHT,'explanation':'Частный случай уточняет общее правило.'}]},{'latency_s':0}
            return {'blocks':[{'id':'b001','title':'Ответственность','summary':'Общее правило и оговорка'}],'risks':[]},{'latency_s':0}
        result=analyze_document(text,client=client,check_relations=True)
        self.assertEqual(len(result['relations']),1)
        self.assertLessEqual(result['relations'][0]['left_end'],result['relations'][0]['right_start'])

    def client(self,prompt,schema,**kwargs):
        if 'pairs' in schema['properties']:
            index=json.loads(prompt.split('<block_index>\n')[1].split('\n</block_index>')[0])
            return {'pairs':[{'left_id':index[0]['id'],'right_id':index[-1]['id']}]},{'latency_s':0}
        if 'relations' in schema['properties']:
            blocks=json.loads(prompt.split('<relation_blocks>\n')[1].split('\n</relation_blocks>')[0])
            left=next(b for b in blocks if LEFT in b['text']);right=next(b for b in blocks if RIGHT in b['text'])
            return {'relations':[{'left_id':left['id'],'right_id':right['id'],'kind':'exception','left_quote':LEFT,'right_quote':RIGHT,'explanation':'Второе условие задаёт исключение из общего освобождения от ответственности.'}]},{'latency_s':0}
        blocks=json.loads(prompt.split('<document_blocks>\n')[1].split('\n</document_blocks>')[0])
        return {'blocks':[{'id':b['id'],'title':'Условия','summary':'Порядок исполнения'} for b in blocks],'risks':[]},{'latency_s':0}

    def test_exception_across_batch_boundary_has_both_verified_sources(self):
        result=analyze_document(TEXT,client=self.client,segmentation='paragraphs',check_relations=True)
        relation=result['relations'][0]
        self.assertNotEqual(relation['left_id'],relation['right_id'])
        self.assertEqual(TEXT[relation['left_start']:relation['left_end']],LEFT)
        self.assertEqual(TEXT[relation['right_start']:relation['right_end']],RIGHT)
        self.assertGreater(relation['right_start'],11000)
        self.assertEqual(result['relation_review']['status'],'completed')

    def test_invented_related_quote_is_rejected(self):
        def invalid(prompt,schema,**kwargs):
            data,meta=self.client(prompt,schema,**kwargs)
            if 'relations' in data:data['relations'][0]['right_quote']='Вымышленная оговорка'
            return data,meta
        with self.assertRaises(ModelError):
            analyze_document(TEXT,client=invalid,segmentation='paragraphs',check_relations=True)

    def test_control_document_does_not_require_a_relation(self):
        def no_relations(prompt,schema,**kwargs):
            if 'relations' in schema['properties']:return {'relations':[]},{'latency_s':0}
            return self.client(prompt,schema,**kwargs)
        result=analyze_document(LEFT+'\n\nСервис доступен круглосуточно.',client=no_relations,segmentation='paragraphs',check_relations=True)
        self.assertEqual(result['relations'],[])


if __name__=='__main__':unittest.main()
