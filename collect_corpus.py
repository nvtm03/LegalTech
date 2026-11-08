"""Download public source snapshots for local research, recording failures honestly."""
import hashlib
import io
import json
from datetime import datetime, timezone
from pathlib import Path
import urllib.request
import argparse

from bs4 import BeautifulSoup
from pypdf import PdfReader
from llm_layer import CTX

ROOT = Path(__file__).resolve().parent / "data/corpus"


def extract_pdf_snapshot(content):
    parts, mapping, cursor = [], [], 0
    for page_number, page in enumerate(PdfReader(io.BytesIO(content)).pages, 1):
        text = page.extract_text() or ''
        mapping.append({'page':page_number, 'start':cursor, 'end':cursor+len(text)})
        parts.append(text)
        cursor += len(text)+2
    return '\n\n'.join(parts), mapping


def collect(*, retry_failed=False):
    raw = ROOT / "raw"
    raw.mkdir(parents=True, exist_ok=True)
    manifest = ROOT / "manifest.json"
    previous = {r["id"]: r for r in json.loads(manifest.read_text())} if manifest.exists() else {}
    records = dict(previous)
    for source in json.loads((ROOT / "sources.json").read_text()):
        old = previous.get(source['id'])
        binary_path = raw / f"{source['id']}.{source['format']}"
        text_path = raw / f"{source['id']}.txt"
        if old:
            if old['status']=='failed' and not retry_failed:
                continue
            if old['status']=='downloaded' and binary_path.exists() and text_path.exists():
                if hashlib.sha256(binary_path.read_bytes()).hexdigest()==old.get('sha256') and hashlib.sha256(text_path.read_bytes()).hexdigest()==old.get('text_sha256'):
                    if source['format']=='pdf' and 'page_map' not in old:
                        extracted, mapping = extract_pdf_snapshot(binary_path.read_bytes())
                        if extracted == text_path.read_text():
                            records[source['id']] = {**old, 'page_map':mapping}
                            manifest.write_text(json.dumps(list(records.values()),ensure_ascii=False,indent=2))
                    continue
        record = {**source, "retrieved_at": datetime.now(timezone.utc).isoformat(),
                  "label": "reference_candidate", "expert_reviewed": False,
                  "license": "Source rights retained by publisher; local research snapshot, not redistributed."}
        try:
            req = urllib.request.Request(source["url"], headers={"User-Agent": "LegalTech-ITMO-research/0.1"})
            with urllib.request.urlopen(req, timeout=30, context=CTX) as response:
                content = response.read(8_000_001)
                record["final_url"] = response.url
                record["content_type"] = response.headers.get("Content-Type", "")
            if len(content) > 8_000_000:
                raise ValueError("source_exceeds_8mb")
            if source["format"] == "pdf":
                if not content.startswith(b"%PDF"):
                    raise ValueError("not_pdf")
                text, page_map = extract_pdf_snapshot(content)
                record['page_map'] = page_map
                record["extraction"] = "pypdf; no OCR; visual review pending"
            else:
                soup = BeautifulSoup(content, "html.parser")
                for element in soup(["script", "style", "noscript", "nav", "header", "footer"]):
                    element.decompose()
                body = soup.find("article") or soup.find("main") or soup.body or soup
                text = body.get_text("\n", strip=True)
                record["extraction"] = "HTML article/main/body; boilerplate review pending"
            if len(text.strip()) < 500 or not any(c in text.lower() for c in ("персональ", "пользовател", "соглашен")):
                raise ValueError("not_a_verified_document")
            binary_hash, text_hash = hashlib.sha256(content).hexdigest(), hashlib.sha256(text.encode()).hexdigest()
            if old and old.get('sha256') and (old['sha256']!=binary_hash or old.get('text_sha256')!=text_hash):
                version=raw/'versions'/source['id']/(binary_hash+'-'+text_hash[:12])
                version.mkdir(parents=True,exist_ok=True)
                (version/('source.'+source['format'])).write_bytes(content)
                (version/'source.txt').write_text(text,encoding='utf-8')
                record={**old,'status':'version_changed','observed_at':record['retrieved_at'],'observed_sha256':binary_hash,
                        'error':'Источник изменился; новая версия сохранена отдельно. Старый снимок не восстановлен.'}
            else:
                binary_path.write_bytes(content)
                text_path.write_text(text, encoding="utf-8")
                record.update(status="downloaded", sha256=binary_hash, text_sha256=text_hash, characters=len(text))
        except Exception as exc:
            record={**(old or record),'status':'failed','error':f"{type(exc).__name__}: {exc}"}
        records[source['id']]=record
        (ROOT / "manifest.json").write_text(json.dumps(list(records.values()), ensure_ascii=False, indent=2), encoding="utf-8")
        print(source["id"], record["status"], record.get("characters", record.get("error")), flush=True)
    return list(records.values())


if __name__ == "__main__":
    parser=argparse.ArgumentParser()
    parser.add_argument('--retry-failed',action='store_true')
    collect(retry_failed=parser.parse_args().retry_failed)
