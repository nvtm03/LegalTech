"""Generate public demo fixtures using authored texts only; strip internal job IDs."""
from datetime import datetime, timezone
from functools import partial
import json
from pathlib import Path
from model_client import generate_json
from pipeline import analyze_document

if __name__=='__main__':
    output=Path('sites/legaltech-demo/src/data.json');output.parent.mkdir(parents=True,exist_ok=True)
    rows=[]
    for case in json.loads(Path('data/demo_cases.json').read_text()):
        result=analyze_document(case['text'],case['doc_type'],model='gemini-3.5-flash-lite',provider='router',check_relations=True,
                                client=partial(generate_json,timeout=120))
        for call in result['calls']:call.pop('job_id',None)
        rows.append({**case,'origin':'authored_synthetic','created_at':datetime.now(timezone.utc).isoformat(),'result':result})
        output.write_text(json.dumps(rows,ensure_ascii=False,indent=2))
        print(case['id'],len(result['blocks']),'blocks',len(result['risks']),'risks',len(result['relations']),'relations',flush=True)
