"""Paired prompt comparison on a declared synthetic development set."""
import argparse
from datetime import datetime, timezone
import json
from pathlib import Path

from model_client import ModelError
from pipeline import analyze_document


def score(expected, predicted):
    expected, predicted = set(expected), set(predicted)
    return {"tp": len(expected & predicted), "fp": len(predicted - expected), "fn": len(expected - predicted)}


def summarize_category_records(records):
    successful = [r for r in records if r['ok']]
    counts = [score(r['expected'], r['predicted']) for r in successful]
    tp, fp, fn = (sum(r[k] for r in counts) for k in ('tp','fp','fn'))
    return {'cases':len(records), 'successes':len(successful), 'technical_errors':len(records)-len(successful),
            'tp':tp,'fp':fp,'fn':fn, 'precision':tp/(tp+fp) if tp+fp else None,
            'recall':tp/(tp+fn) if tp+fn else None,
            'exact_category_matches':sum(set(r['expected'])==set(r['predicted']) for r in successful)}


def summarize_target_records(records):
    """Only the labelled target pattern is scored; missing responses remain errors."""
    counts = dict(tp=0, tn=0, fp=0, fn=0, errors=0)
    for row in records:
        if not row['ok']:
            counts['errors'] += 1
            continue
        predicted = row['target_category'] in row['predicted']
        expected = row['expected_target_present']
        key = ('tp' if predicted else 'fn') if expected else ('fp' if predicted else 'tn')
        counts[key] += 1
    counts['cases'] = len(records)
    counts['correct_over_all_cases'] = (counts['tp'] + counts['tn'])/len(records) if records else None
    return counts


def score_end_to_end(case,result):
    if result is None:return {'ok':False,'matches_expected':False,'target_found':False,'mislocalized':0,'outcome':'technical_error'}
    same_category=[r for r in result['risks'] if r['category']==case['target_category']]
    localized=[r for r in same_category if r['quote_start']<case['target_end'] and r['quote_end']>case['target_start']]
    expected=set(case.get('reference_starts',[]))-{0}
    predicted={b['start'] for b in result['blocks']}-{0}
    # Coarse author reference, exact source-coordinate tolerance, one-to-one matches.
    unmatched=set(expected);tp=0
    for start in sorted(predicted):
        candidates=sorted(s for s in unmatched if abs(s-start)<=2)
        if candidates:unmatched.remove(candidates[0]);tp+=1
    found=bool(localized)
    correct = found if case['expected_target_present'] else not same_category
    outcome = ('hit' if found else 'mislocalized' if same_category else 'miss') if case['expected_target_present'] else ('false_alarm' if found else 'mislocalized' if same_category else 'clean_control')
    return {'ok':True,'matches_expected':correct,'target_found':found,'outcome':outcome,
            'mislocalized':len(same_category)-len(localized),'boundary_tp':tp,'boundary_fp':len(predicted)-tp,'boundary_fn':len(unmatched)}


def evaluate(cases, *, model="gemini-3.1-flash-lite", provider="router", out=Path("results/prompt_comparison.json")):
    records = []
    result = {"created_at": datetime.now(timezone.utc).isoformat(), "dataset": "synthetic-development-v1",
              "scope": "Категории риска на синтетических фрагментах. Не юридическая точность и не независимый тест.",
              "model": model, "provider": provider, "records": records, "summary": {}}
    out.parent.mkdir(parents=True, exist_ok=True)
    for case in cases:
        for variant in ("baseline", "checklist"):
            record = {"case_id": case["id"], "family_id": case["family_id"], "doc_type": case["doc_type"],
                      "variant": variant, "expected": case["expected_categories"]}
            try:
                answer = analyze_document(case["text"], case["doc_type"], model=model, provider=provider, variant=variant, segmentation="paragraphs")
                predicted = sorted({r["category"] for r in answer["risks"]})
                record.update(ok=True, predicted=predicted, analysis=answer, **score(case["expected_categories"], predicted))
            except (ModelError, ValueError) as exc:
                record.update(ok=False, error=str(exc), predicted=[], **score(case["expected_categories"], []))
            records.append(record)
            for name in ("baseline", "checklist"):
                rows = [r for r in records if r["variant"] == name]
                result["summary"][name] = summarize_category_records(rows)
            out.write_text(json.dumps(result, ensure_ascii=False, indent=2), encoding="utf-8")
            print(case["id"], variant, "ok=" + str(record["ok"]), "predicted=" + str(record["predicted"]), flush=True)
    return result


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--limit", type=int, default=6)
    parser.add_argument("--model", default="gemini-3.1-flash-lite")
    parser.add_argument("--provider", choices=["router", "google"], default="router")
    parser.add_argument("--output", type=Path, default=Path("results/prompt_comparison.json"))
    args = parser.parse_args()
    cases = json.loads(Path("data/evaluation/cases.json").read_text())
    evaluate(cases[:args.limit], model=args.model, provider=args.provider, out=args.output)
