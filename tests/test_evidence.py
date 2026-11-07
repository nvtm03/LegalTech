import unittest
from model_client import ModelError
from pipeline import validate_answer


class EvidenceTests(unittest.TestCase):
    def answer(self, quote):
        return {'blocks':[{'id':'b001','title':'Отзыв','summary':'Обращение'}],
                'risks':[{'block_id':'b001','category':'withdrawal','severity':'medium','quote':quote,
                          'reason':'Проверить форму обращения','suggestion':'Уточнить процедуру','related_block_ids':[]}]}

    # Would catch rejecting PDF word-spacing artifacts or displaying a reconstructed quote as original evidence.
    def test_pdf_whitespace_is_restored_to_exact_original_substring(self):
        blocks=[{'id':'b001','start':200,'text':'Обращение: электронного доку мента,\n подписанного электронной подписью.'}]
        try:
            result=validate_answer(self.answer('электронного документа, подписанного электронной подписью.'),blocks,allow_pdf_whitespace=True)
        except ModelError:
            self.fail('Отклонена цитата, отличающаяся только пробелами PDF.')
        risk=result['risks'][0]
        self.assertEqual(risk['quote'],'электронного доку мента,\n подписанного электронной подписью.')
        self.assertEqual(risk['quote_start'],211)
        self.assertEqual(risk['quote_match'],'whitespace_restored')

    def test_non_whitespace_character_changes_still_rejected(self):
        blocks=[{'id':'b001','start':0,'text':'Хранение не допускается.'}]
        with self.assertRaises(ModelError):
            validate_answer(self.answer('Хранение допускается.'),blocks)

    def test_ambiguous_normalized_quote_is_rejected(self):
        blocks=[{'id':'b001','start':0,'text':'один\nгод либо один\tгод'}]
        with self.assertRaises(ModelError):
            validate_answer(self.answer('один год'),blocks)

    def test_repeated_exact_quote_does_not_choose_first_occurrence(self):
        blocks=[{'id':'b001','text':'Оплата после отказа. Отмена после отказа.','start':0}]
        with self.assertRaises(ModelError): validate_answer(self.answer('после отказа'),blocks)

    def test_empty_reason_and_suggestion_are_rejected(self):
        for field in ('reason','suggestion'):
            with self.subTest(field=field):
                answer=self.answer('Нужна проверка')
                answer['risks'][0][field]='   '
                with self.assertRaises(ModelError): validate_answer(answer,[{'id':'b001','text':'Нужна проверка','start':0}])

    def test_partial_number_is_not_evidence_for_a_different_amount(self):
        with self.assertRaises(ModelError):
            validate_answer(self.answer('1 00'),[{'id':'b001','text':'Штраф 1 000 рублей.','start':0}])

    def test_plain_text_does_not_silently_remove_spaces_inside_words(self):
        with self.assertRaises(ModelError):
            validate_answer(self.answer('незаконно'),[{'id':'b001','text':'не законно','start':0}])

    def test_layout_whitespace_can_be_restored_without_joining_words(self):
        try:
            result=validate_answer(self.answer('письмо на адрес'),[{'id':'b001','text':'письмо\u00a0на\nадрес','start':0}])
        except ModelError:
            self.fail('Эквивалентные пробелы и переносы отклонены.')
        self.assertEqual(result['risks'][0]['quote'],'письмо\u00a0на\nадрес')


if __name__=='__main__': unittest.main()
