"""Reproduce a frozen composite benchmark without distributing source text."""
import hashlib
import json
from pathlib import Path
from build_benchmark import build_pairs

def validate_families(specs, development):
    if {s['family_id'] for s in specs} & {s['family_id'] for s in development}:
        raise ValueError('Source family leakage')


if __name__=='__main__':
    specs=json.loads(Path('data/evaluation/heldout_specs.json').read_text())
    validate_families(specs, json.loads(Path('data/evaluation/pair_specs.json').read_text()))
    rows=build_pairs(specs,Path('data/corpus/raw'))
    prefix='1. Назначение сервиса\nСервис предоставляет пользователю информационные материалы по его запросу.\n\n2. Основное условие\n'
    suffix='\n\n3. Контакты\nВопросы о работе сервиса принимаются по адресу help@example.org.'
    for row in rows:
        excerpt=row['text'];row['text']=prefix+excerpt+suffix
        row.update(input_origin='pdf_extracted' if row['source_id']=='selectel_consent' else 'text',target_start=len(prefix),target_end=len(prefix)+len(excerpt),
                   reference_starts=[0,prefix.index('2. Основное условие'),len(prefix)+len(excerpt)+2],origin='composite_real_excerpt_and_authored_context',
                   annotation_scope='Only the labelled pattern within the source excerpt. Coarse author section boundaries, not independent legal review.')
        row['text_sha256']=hashlib.sha256(row['text'].encode()).hexdigest()
    target=Path('data/corpus/derived/heldout-v1.json');target.parent.mkdir(parents=True,exist_ok=True)
    target.write_text(json.dumps(rows,ensure_ascii=False,indent=2))
    print('Cases:',len(rows),'families:',len({r['family_id'] for r in rows}))
