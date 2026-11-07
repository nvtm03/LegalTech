"""Small paired pilot, with only the declared target category scored."""
import argparse
from datetime import datetime, timezone
from functools import partial
import hashlib
import json
from pathlib import Path
import sys

from evaluate import summarize_target_records
from model_client import ModelError, generate_json
from pipeline import analyze_document, SYSTEM, CHECKLIST, SCHEMA


def run(cases, output, *, model='gemini-3.1-flash-lite', timeout=120):
    if output.exists():
        raise ValueError('Файл результатов уже существует. Выберите новое имя --output.')
    fingerprints = {name: hashlib.sha256(Path(name).read_bytes()).hexdigest() for name in
                    ('pipeline.py','model_client.py','evaluate.py','evaluate_pairs.py','data/evaluation/pair_specs.json','requirements.lock.txt')}
    result = {'created_at':datetime.now(timezone.utc).isoformat(), 'dataset':'real-derived-target-pilot-v1',
              'scope':'Presence of a labelled drafting-risk pattern in excerpts; not full legal accuracy. Development pilot, no significance claims.',
              'independent_families':sorted({c['family_id'] for c in cases}), 'model':model,'provider':'router',
              'segmentation':'paragraphs-v1 (identical for both risk prompts, to isolate prompt differences)',
              'timeout_seconds':timeout,'code_sha256':fingerprints,'python':sys.version,
              'checklist_sha256':hashlib.sha256((SYSTEM+CHECKLIST+json.dumps(SCHEMA,sort_keys=True)).encode()).hexdigest(),
              'cases_sha256':hashlib.sha256(json.dumps(cases,sort_keys=True,ensure_ascii=False).encode()).hexdigest(),
              'records':[], 'summary':{}}
    raw_records = []
    raw_path = output.parent/'private'/(output.stem+'-raw.json')
    output.parent.mkdir(parents=True,exist_ok=True)
    raw_path.parent.mkdir(parents=True,exist_ok=True)
    for index, case in enumerate(cases):
        # Alternate order to avoid assigning one prompt all the earlier queue slots.
        variants = ('baseline','checklist') if index % 2 == 0 else ('checklist','baseline')
        for variant in variants:
            record = {k:case[k] for k in ('id','pair_id','source_id','family_id','doc_type','split','text_sha256','target_category','expected_target_present')}
            record.update(variant=variant,order=len(result['records'])+1)
            try:
                answer=analyze_document(case['text'],case['doc_type'],provider='router',model=model,variant=variant,
                                        segmentation='paragraphs',client=partial(generate_json,timeout=timeout))
                record.update(ok=True,predicted=sorted({r['category'] for r in answer['risks']}),calls=answer['calls'])
                raw_records.append({'id':case['id'],'variant':variant,'analysis':answer})
            except (ModelError,ValueError) as exc:
                record.update(ok=False,predicted=[],error=str(exc))
            result['records'].append(record)
            for name in ('baseline','checklist'):
                rows=[r for r in result['records'] if r['variant']==name]
                result['summary'][name]=summarize_target_records(rows)
            raw_path.write_text(json.dumps(raw_records,ensure_ascii=False,indent=2),encoding='utf-8')
            output.write_text(json.dumps(result,ensure_ascii=False,indent=2),encoding='utf-8')
            print(case['id'],variant,'ok='+str(record['ok']),'target='+str(case['target_category'] in record['predicted']),flush=True)
    result['finished_at']=datetime.now(timezone.utc).isoformat()
    output.write_text(json.dumps(result,ensure_ascii=False,indent=2),encoding='utf-8')
    return result


if __name__=='__main__':
    parser=argparse.ArgumentParser()
    parser.add_argument('--cases',type=Path,default=Path('data/corpus/derived/cases.json'))
    parser.add_argument('--output',type=Path,default=Path('results/real-derived-pilot-v1.json'))
    parser.add_argument('--timeout',type=float,default=120)
    args=parser.parse_args()
    run(json.loads(args.cases.read_text()),args.output,timeout=args.timeout)
