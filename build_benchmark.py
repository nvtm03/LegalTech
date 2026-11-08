"""Rebuild local, source-derived pairs from immutable snapshots and explicit edits."""
import argparse
import hashlib
import json
from pathlib import Path
import re
import sys


def build_pairs(specs, source_dir):
    rows, ids, family_splits = [], set(), {}
    for spec in specs:
        if spec['id'] in ids:
            raise ValueError('Повторный id в спецификации.')
        ids.add(spec['id'])
        source_id = spec['source_id']
        if not re.fullmatch(r'[a-zA-Z0-9_]+', source_id):
            raise ValueError('Неверный идентификатор источника.')
        text = (source_dir / f'{source_id}.txt').read_text(encoding='utf-8')
        if hashlib.sha256(text.encode()).hexdigest() != spec['source_text_sha256']:
            raise ValueError('SHA-256 источника изменился; пересмотрите границы и разметку.')
        start, end = spec['start'], spec['end']
        if not isinstance(start, int) or not isinstance(end, int) or not 0 <= start < end <= len(text):
            raise ValueError('Границы фрагмента вне документа.')
        excerpt = text[start:end]
        if not spec['replace'] or excerpt.count(spec['replace']) != 1:
            raise ValueError('Заменяемый фрагмент должен встречаться ровно один раз.')
        if spec['replacement'] == spec['replace']:
            raise ValueError('Мутация не меняет текст.')
        family = spec['family_id']
        if family in family_splits and family_splits[family] != spec['split']:
            raise ValueError('Утечка: одно семейство попало в разные разбиения.')
        family_splits[family] = spec['split']
        common = {k: spec[k] for k in ('source_id','source_text_sha256','doc_type','family_id','split','start','end','target_category')}
        common.update(annotation_scope='Only presence of the specified drafting-risk pattern, not full legal compliance.', expert_reviewed=False)
        for kind, value, expected in [('original',excerpt,False), ('mutation',excerpt.replace(spec['replace'],spec['replacement'],1),True)]:
            rows.append({**common, 'id':spec['id']+'_'+kind, 'pair_id':spec['id'], 'origin':'real_excerpt' if kind=='original' else 'synthetic_mutation_of_real_excerpt',
                         'text':value, 'text_sha256':hashlib.sha256(value.encode()).hexdigest(),'expected_target_present':expected})
    return rows


if __name__ == '__main__':
    parser=argparse.ArgumentParser()
    parser.add_argument('--source-dir',type=Path,default=Path('data/corpus/raw'))
    parser.add_argument('--specs',type=Path,default=Path('data/evaluation/pair_specs.json'))
    parser.add_argument('--output',type=Path,default=Path('data/corpus/derived/cases.json'))
    args=parser.parse_args()
    try:
        rows=build_pairs(json.loads(args.specs.read_text()),args.source_dir)
        args.output.parent.mkdir(parents=True,exist_ok=True)
        args.output.write_text(json.dumps(rows,ensure_ascii=False,indent=2),encoding='utf-8')
        print(f'Создано {len(rows)} фрагментов, {len(rows)//2} пар.')
    except (ValueError,KeyError,OSError) as exc:
        print(str(exc),file=sys.stderr)
        sys.exit(1)
