"""Run the same pipeline as the app on a local UTF-8 document."""
import argparse
from functools import partial
import json
from pathlib import Path

from model_client import generate_json
from pipeline import analyze_document

if __name__ == '__main__':
    parser=argparse.ArgumentParser()
    parser.add_argument('input',type=Path)
    parser.add_argument('--output',type=Path,required=True)
    parser.add_argument('--doc-type',default='unknown',choices=['consent','privacy','terms','unknown'])
    parser.add_argument('--model',default='gemini-3.1-flash-lite')
    parser.add_argument('--timeout',type=float,default=120)
    parser.add_argument('--input-origin',choices=['text','pdf_extracted'],default='text')
    parser.add_argument('--skip-relations',action='store_true')
    args=parser.parse_args()
    if args.output.exists():
        parser.error('Выберите новое имя результата: файл уже существует.')
    result=analyze_document(args.input.read_text(encoding='utf-8'),args.doc_type,provider='router',model=args.model,input_origin=args.input_origin,check_relations=not args.skip_relations,
                            client=partial(generate_json,timeout=args.timeout))
    args.output.parent.mkdir(parents=True,exist_ok=True)
    args.output.write_text(json.dumps(result,ensure_ascii=False,indent=2),encoding='utf-8')
    print(json.dumps({'blocks':len(result['blocks']),'risks':len(result['risks']),'calls':len(result['calls']),'segmentation':result['segmentation_version']},ensure_ascii=False))
