"""Versioned E2E pilot; explicit API runs and an entirely offline summary mode."""
import argparse
from datetime import datetime, timezone
import hashlib
import json
from pathlib import Path

from evaluate import score_end_to_end
from model_client import generate_json, ModelError
from pipeline import analyze_document
from prepare_e2e_cases import validate_families


def summarize(records):
    summary = {}
    for key in sorted({r['model']+'/'+r['segmentation'] for r in records}):
        rows = [r for r in records if r['model']+'/'+r['segmentation']==key]
        successful = [r for r in rows if r['ok']]
        summary[key] = {
            'cases':len(rows), 'successful':len(successful), 'technical_errors':len(rows)-len(successful),
            'localized_correct':sum(bool(r['target_found']) if r['expected_target_present'] else not(r['target_found'] or r['mislocalized']) for r in successful),
            'missed_injections':sum(r['expected_target_present'] and not r['target_found'] for r in successful),
            'flagged_controls':sum(not r['expected_target_present'] and bool(r['target_found'] or r['mislocalized']) for r in successful),
            'mislocalized_findings':sum(r['mislocalized'] for r in successful),
            'partial_results':sum(r.get('partial',False) for r in successful),
            'positive_cases':sum(r['expected_target_present'] for r in rows),
            'control_cases':sum(not r['expected_target_present'] for r in rows),
            **{k:sum(r.get(k,0) for r in successful) for k in ('boundary_tp','boundary_fp','boundary_fn')},
        }
    return summary


def public_data(value):
    if isinstance(value,dict):
        return {k:public_data(v) for k,v in value.items() if k not in ('job_id','analysis_id')}
    if isinstance(value,list):
        return [public_data(v) for v in value]
    return value


def main():
    parser=argparse.ArgumentParser()
    parser.add_argument('--output',type=Path,required=True,help='New result path; existing files are never overwritten.')
    parser.add_argument('--summarize',type=Path,help='Reaggregate saved records without any model calls.')
    parser.add_argument('--models',nargs='+',default=['gemini-3.5-flash-lite','gemma-4-26b-a4b-it'])
    parser.add_argument('--segmentation',choices=['semantic','paragraphs'],default='semantic')
    parser.add_argument('--timeout',type=int,default=300)
    parser.add_argument('--cases',type=Path,default=Path('data/corpus/derived/heldout-v1.json'))
    args=parser.parse_args()
    out=args.output
    if out.exists():raise SystemExit('Result exists: choose a new result path instead of overwriting.')
    out.parent.mkdir(parents=True,exist_ok=True)
    if args.summarize:
        result=json.loads(args.summarize.read_text())
        result['summary']=summarize(result['records'])
        result['reaggregated_at']=datetime.now(timezone.utc).isoformat()
        result['source_result']=str(args.summarize)
        out.write_text(json.dumps(public_data(result),ensure_ascii=False,indent=2))
        return
    if args.timeout<=0:raise SystemExit('Timeout must be positive')
    cases=json.loads(args.cases.read_text())
    development=json.loads(Path('data/evaluation/pair_specs.json').read_text())
    validate_families(cases,development)
    result={'created_at':datetime.now(timezone.utc).isoformat(),'dataset':'composite-v1-reused-diagnostic',
        'families':sorted({c['family_id'] for c in cases}),
        'limitations':['Six composite excerpts from two source families; author labels, no expert legal validation.',
            'This set was previously inspected; this is a diagnostic rerun, not a new untouched held-out test.',
            'Same cases, segmentation, risk prompt and timeout for both models. Alternating model order by case.',
            'One run per model and case. No significance or model superiority claim. Partial relations are reported separately.'],
        'dataset_sha256':hashlib.sha256(args.cases.read_bytes()).hexdigest(),
        'code_sha256':{p:hashlib.sha256(Path(p).read_bytes()).hexdigest() for p in ('pipeline.py','model_client.py','evaluate.py','evaluate_e2e.py','requirements.lock.txt')},
        'records':[], 'summary':{}}
    private=Path('results/private')/out.stem
    private.mkdir(parents=True,exist_ok=True)
    for i,case in enumerate(cases):
        models=args.models if i%2==0 else list(reversed(args.models))
        for model in models:
            record={k:case[k] for k in ('id','pair_id','family_id','source_id','doc_type','text_sha256','target_category','expected_target_present','target_start','target_end')}
            record.update(segmentation=args.segmentation,model=model,timeout_seconds=args.timeout,relations=True)
            raw_path=private/(case['id']+'-'+args.segmentation+'-'+model+'.json')
            trace=[]
            cache_path=raw_path.with_suffix('.checkpoint.json')
            cache=json.loads(cache_path.read_text()) if cache_path.exists() else {}
            def checkpoint(key,value=None):
                if value is not None:
                    cache[key]=value
                    cache_path.write_text(json.dumps(cache,ensure_ascii=False))
                    cache_path.chmod(0o600)
                return cache.get(key)
            def client(prompt,schema,**kwargs):
                answer,meta=generate_json(prompt,schema,timeout=args.timeout,checkpoint=checkpoint,**kwargs)
                trace.append({'answer':answer,'metadata':meta})
                raw_path.with_suffix('.trace.json').write_text(json.dumps(trace,ensure_ascii=False,indent=2))
                return answer,meta
            try:
                answer=analyze_document(case['text'],case['doc_type'],provider='router',model=model,
                    segmentation=args.segmentation,input_origin=case['input_origin'],check_relations=True,client=client)
                raw_path.write_text(json.dumps(answer,ensure_ascii=False,indent=2))
                record.update(score_end_to_end(case,answer),calls=answer['calls'],blocks=len(answer['blocks']),
                    relations_found=len(answer['relations']),partial=answer.get('partial',False),relation_review=answer['relation_review'])
            except (ModelError,ValueError) as exc:
                record.update(score_end_to_end(case,None),error=str(exc))
            result['records'].append(record)
            result['summary']=summarize(result['records'])
            out.write_text(json.dumps(public_data(result),ensure_ascii=False,indent=2))
            print(model,case['id'],'outcome='+record['outcome'],flush=True)
    result['finished_at']=datetime.now(timezone.utc).isoformat()
    out.write_text(json.dumps(public_data(result),ensure_ascii=False,indent=2))


if __name__=='__main__':main()
