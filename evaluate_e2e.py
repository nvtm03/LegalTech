"""Frozen end-to-end pilot: localization, coarse boundaries, ablation, compatibility."""
from datetime import datetime, timezone
from functools import partial
import hashlib
import json
from pathlib import Path

from evaluate import score_end_to_end
from model_client import generate_json, ModelError
from pipeline import analyze_document

if __name__=='__main__':
    cases_path=Path('data/corpus/derived/heldout-v1.json')
    cases=json.loads(cases_path.read_text())
    out=Path('results/e2e-heldout-v1.json')
    if out.exists():raise SystemExit('Result exists: choose a new protocol/version instead of overwriting.')
    result={'created_at':datetime.now(timezone.utc).isoformat(),'dataset':'heldout-composite-v1','families':sorted({c['family_id'] for c in cases}),
            'limitations':['Six composite excerpts from two source families; author labels, no expert legal validation.',
                            'Not a full-document legal benchmark. Coarse heading boundaries are an author reference.',
                            'Paragraph ablation uses only three injected cases; Gemma is one compatibility check. No significance or model superiority claim.'],
            'dataset_sha256':hashlib.sha256(cases_path.read_bytes()).hexdigest(),
            'code_sha256':{p:hashlib.sha256(Path(p).read_bytes()).hexdigest() for p in ('pipeline.py','model_client.py','evaluate.py','evaluate_e2e.py','data/evaluation/heldout_specs.json','requirements.lock.txt')},
            'records':[],'summary':{}}
    runs=[('semantic',c,'gemini-3.5-flash-lite') for c in cases]
    runs += [('paragraphs',c,'gemini-3.5-flash-lite') for c in cases if c['expected_target_present']]
    runs += [('semantic',next(c for c in cases if c['expected_target_present']),'gemma-4-26b-a4b-it')]
    for segmentation,case,model in runs:
        record={k:case[k] for k in ('id','pair_id','family_id','source_id','doc_type','text_sha256','target_category','expected_target_present','target_start','target_end')}
        record.update(segmentation=segmentation,model=model,timeout_seconds=120,relations=True)
        raw_path=Path('results/private/e2e')/(case['id']+'-'+segmentation+'-'+model+'.json')
        raw_path.parent.mkdir(parents=True,exist_ok=True)
        trace=[]
        def client(prompt,schema,**kwargs):
            answer,meta=generate_json(prompt,schema,timeout=120,**kwargs)
            trace.append({'answer':answer,'metadata':meta})
            raw_path.with_suffix('.trace.json').write_text(json.dumps(trace,ensure_ascii=False,indent=2))
            return answer,meta
        try:
            answer=analyze_document(case['text'],case['doc_type'],provider='router',model=model,segmentation=segmentation,
                                    input_origin=case['input_origin'],check_relations=True,client=client)
            raw_path.write_text(json.dumps(answer,ensure_ascii=False,indent=2))
            record.update(score_end_to_end(case,answer),calls=answer['calls'],blocks=len(answer['blocks']),relations_found=len(answer['relations']))
        except (ModelError,ValueError) as exc:
            record.update(score_end_to_end(case,None),error=str(exc))
        result['records'].append(record)
        for key in sorted({r['model']+'/'+r['segmentation'] for r in result['records']}):
            rows=[r for r in result['records'] if r['model']+'/'+r['segmentation']==key]
            result['summary'][key]={'cases':len(rows),'successful':sum(r['ok'] for r in rows),'localized_correct':sum(r['matches_expected'] for r in rows),
                'missed_injections':sum(r['expected_target_present'] and not r['target_found'] for r in rows),
                'flagged_controls':sum(not r['expected_target_present'] and r['target_found'] for r in rows),
                'mislocalized_findings':sum(r['mislocalized'] for r in rows),
                **{k:sum(r.get(k,0) for r in rows) for k in ('boundary_tp','boundary_fp','boundary_fn')}}
        out.write_text(json.dumps(result,ensure_ascii=False,indent=2))
        print(model,segmentation,case['id'],'ok='+str(record['ok']),'localized_correct='+str(record['matches_expected']),flush=True)
    result['finished_at']=datetime.now(timezone.utc).isoformat()
    out.write_text(json.dumps(result,ensure_ascii=False,indent=2))
