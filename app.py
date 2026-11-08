"""Local workbench. Run one worker, bound to 127.0.0.1; not a public deployment."""
from contextlib import asynccontextmanager
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timezone
import json
import logging
import os
from pathlib import Path
import sqlite3
import hashlib
import secrets
import re
from threading import Lock
from typing import Literal
from uuid import uuid4
from functools import partial

from fastapi import FastAPI, HTTPException, Request
from fastapi.responses import FileResponse, JSONResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, ConfigDict, Field, field_validator
from starlette.middleware.trustedhost import TrustedHostMiddleware

from llm_layer import load_env
from model_client import ModelError, generate_json
from pipeline import analyze_document

ROOT = Path(__file__).resolve().parent
MODELS = ["gemini-3.1-flash-lite", "gemini-3.5-flash-lite", "gemini-3.6-flash", "gemini-3.8-flash", "gemma-4-26b-a4b-it", "gemma-4-31b-it"]
log = logging.getLogger("legaltech")


class AnalysisRequest(BaseModel):
    model_config = ConfigDict(extra='forbid')
    text: str = Field(min_length=20, max_length=120000)
    doc_type: Literal["consent", "terms", "privacy", "unknown"] = "unknown"
    model: str = "gemini-3.1-flash-lite"
    provider: Literal["router", "google"] = "router"

    @field_validator("model")
    @classmethod
    def valid_model(cls, value):
        if value not in MODELS:
            raise ValueError("Выберите доступную модель.")
        return value

    @field_validator("text")
    @classmethod
    def meaningful_text(cls, value):
        if len(value.strip()) < 20:
            raise ValueError("Добавьте хотя бы 20 символов текста.")
        return value


class BodyLimitMiddleware:
    def __init__(self, app, limit=1000000):
        self.app, self.limit = app, limit

    async def __call__(self, scope, receive, send):
        if scope['type'] != 'http' or scope['method'] not in ('POST','PUT','PATCH'):
            return await self.app(scope,receive,send)
        chunks, size = [], 0
        while True:
            event=await receive()
            if event['type']=='http.disconnect':return
            size+=len(event.get('body',b''))
            if size>self.limit:
                return await JSONResponse({'detail':'Документ слишком большой.'},status_code=413)(scope,receive,send)
            chunks.append(event.get('body',b''))
            if not event.get('more_body',False):break
        body=b''.join(chunks)
        sent=False
        async def replay():
            nonlocal sent
            if not sent:
                sent=True
                return {'type':'http.request','body':body,'more_body':False}
            return await receive()
        return await self.app(scope,replay,send)


def create_app(db_path=None):
    lock = Lock()

    @asynccontextmanager
    async def lifespan(app):
        load_env(str(ROOT / ".env"))
        path = Path(db_path or ROOT / "data/runtime/jobs.sqlite3")
        path.parent.mkdir(parents=True, exist_ok=True)
        path.parent.chmod(0o700)
        app.state.db = sqlite3.connect(path, check_same_thread=False)
        path.chmod(0o600)
        app.state.db.row_factory = sqlite3.Row
        app.state.db.execute("CREATE TABLE IF NOT EXISTS jobs (id TEXT PRIMARY KEY, status TEXT, created_at TEXT, progress TEXT, result TEXT, error TEXT)")
        columns={row[1] for row in app.state.db.execute('PRAGMA table_info(jobs)')}
        for column in ('owner','input','retry_action','failed_call_key'):
            if column not in columns:
                app.state.db.execute(f'ALTER TABLE jobs ADD COLUMN {column} TEXT')
        app.state.db.execute('CREATE TABLE IF NOT EXISTS model_calls (analysis_id TEXT, call_key TEXT, job_json TEXT, PRIMARY KEY(analysis_id,call_key))')
        app.state.db.execute("UPDATE jobs SET status='failed', error='Приложение было перезапущено. Запустите анализ снова.' WHERE status IN ('queued','running')")
        app.state.db.commit()
        app.state.pool = ThreadPoolExecutor(max_workers=2, thread_name_prefix="analysis")
        yield
        app.state.pool.shutdown(wait=True, cancel_futures=True)
        app.state.db.close()

    def purge_expired():
        # Seven days matches the session lifetime. Cleanup also removes orphaned traces.
        with lock:
            app.state.db.execute("DELETE FROM jobs WHERE status NOT IN ('queued','running') AND julianday(created_at) < julianday('now','-7 days')")
            app.state.db.execute('DELETE FROM model_calls WHERE analysis_id NOT IN (SELECT id FROM jobs)')
            app.state.db.commit()

    app = FastAPI(title="LegalTech Workbench", lifespan=lifespan)
    app.add_middleware(TrustedHostMiddleware, allowed_hosts=["127.0.0.1", "localhost", "[::1]"])
    app.add_middleware(BodyLimitMiddleware)

    @app.middleware("http")
    async def same_origin(request: Request, call_next):
        purge_expired()
        session=request.cookies.get('legaltech-session','')
        if not re.fullmatch('[0-9a-f]{64}',session):
            session=secrets.token_hex(32)
        request.state.owner=hashlib.sha256(session.encode()).hexdigest()
        origin = request.headers.get("origin")
        if origin and request.method not in ("GET", "HEAD", "OPTIONS"):
            allowed = {f"http://{request.headers.get('host')}", "http://localhost:5173", "http://127.0.0.1:5173"}
            if origin not in allowed:
                return JSONResponse({"detail": "Откройте приложение в локальной вкладке."}, status_code=403)
        try:
            content_length = int(request.headers.get("content-length", "0") or 0)
        except ValueError:
            return JSONResponse({"detail": "Некорректный размер запроса."}, status_code=400)
        if content_length > 1000000:
            return JSONResponse({"detail": "Документ слишком большой."}, status_code=413)
        response = await call_next(request)
        if request.cookies.get('legaltech-session') != session:
            response.set_cookie('legaltech-session',session,httponly=True,samesite='strict',max_age=604800)
        response.headers["X-Content-Type-Options"] = "nosniff"
        response.headers["Cache-Control"] = "no-store"
        return response

    def update(job_id, **values):
        with lock:
            columns = ", ".join(f"{k}=?" for k in values)
            app.state.db.execute(f"UPDATE jobs SET {columns} WHERE id=?", [*values.values(), job_id])
            app.state.db.commit()

    def work(job_id, payload):
        update(job_id, status="running")
        last_call_key = None
        def checkpoint(key,value=None):
            nonlocal last_call_key
            last_call_key = key
            with lock:
                if value is not None:
                    app.state.db.execute('INSERT INTO model_calls VALUES (?,?,?) ON CONFLICT(analysis_id,call_key) DO UPDATE SET job_json=excluded.job_json',
                                         (job_id,key,json.dumps(value,ensure_ascii=False)))
                    app.state.db.commit()
                row=app.state.db.execute('SELECT job_json FROM model_calls WHERE analysis_id=? AND call_key=?',(job_id,key)).fetchone()
            return json.loads(row['job_json']) if row else None
        try:
            result = analyze_document(payload.text, payload.doc_type, model=payload.model, provider=payload.provider,
                                      check_relations=True,
                                      client=partial(generate_json,checkpoint=checkpoint),
                                      stage_progress=lambda stage,done,total:update(job_id,progress=json.dumps({'stage':stage,'done':done,'total':total})))
            is_partial = result.get('partial', False)
            review = result.get('relation_review', {})
            update(job_id, status='partial' if is_partial else 'done', result=json.dumps(result, ensure_ascii=False),
                   retry_action=review.get('retry_action', 'retry') if is_partial else None,
                   failed_call_key=last_call_key if is_partial else None)
        except (ModelError, ValueError) as exc:
            update(job_id, status="failed", error=str(exc), retry_action=getattr(exc,"retry_action","retry"), failed_call_key=last_call_key)
        except Exception:
            log.exception("Analysis failed: %s", job_id)
            update(job_id, status="failed", error="Не удалось обработать документ. Повторите анализ или проверьте журнал приложения.")

    @app.get("/api/health")
    def health():
        return {"ok": True, "router_configured": bool(os.getenv("ROUTER_API_KEY")),
                "google_configured": bool(os.getenv("GEMINI_API_KEY")), "models": MODELS}

    @app.post("/api/analyses", status_code=202)
    def create_analysis(payload: AnalysisRequest, request: Request):
        key = "ROUTER_API_KEY" if payload.provider == "router" else "GEMINI_API_KEY"
        if not os.getenv(key):
            raise HTTPException(503, "Сначала настройте ключ выбранного провайдера в .env.")
        job_id = uuid4().hex
        with lock:
            active = app.state.db.execute("SELECT COUNT(*) FROM jobs WHERE status IN ('queued','running')").fetchone()[0]
            if active >= 2:
                raise HTTPException(429, "Дождитесь завершения текущих анализов.")
            app.state.db.execute("INSERT INTO jobs (id,status,created_at,progress,owner,input) VALUES (?, 'queued', ?, ?, ?, ?)",
                                 (job_id, datetime.now(timezone.utc).isoformat(), '{"done":0,"total":0}',request.state.owner,payload.model_dump_json()))
            app.state.db.commit()
        app.state.pool.submit(work, job_id, payload)
        return {"id": job_id, "status": "queued"}

    @app.get('/api/analyses')
    def list_analyses(request: Request):
        with lock:
            rows = app.state.db.execute('SELECT id,status,created_at FROM jobs WHERE owner=? ORDER BY created_at DESC LIMIT 100', (request.state.owner,)).fetchall()
        return {'analyses':[dict(row) for row in rows], 'retention_days':7}

    @app.get("/api/analyses/{job_id}")
    def get_analysis(job_id: str, request: Request):
        with lock:
            row = app.state.db.execute("SELECT * FROM jobs WHERE id=? AND owner=?", (job_id,request.state.owner)).fetchone()
        if not row:
            raise HTTPException(404, "Анализ не найден. Запустите новый.")
        return {"id": row["id"], "status": row["status"], "created_at": row["created_at"],
                "progress": json.loads(row["progress"]), "input":json.loads(row['input']) if row['input'] else None,
                "result": json.loads(row["result"]) if row["result"] else None, "error": row["error"], "retry_action":row["retry_action"] or "resume"}

    @app.delete('/api/analyses/{job_id}',status_code=204)
    def delete_analysis(job_id: str, request: Request):
        with lock:
            row=app.state.db.execute('SELECT status FROM jobs WHERE id=? AND owner=?',(job_id,request.state.owner)).fetchone()
            if not row:raise HTTPException(404,'Анализ не найден.')
            if row['status'] in ('queued','running'):raise HTTPException(409,'Сначала дождитесь завершения анализа.')
            app.state.db.execute('DELETE FROM jobs WHERE id=? AND owner=?',(job_id,request.state.owner))
            app.state.db.execute('DELETE FROM model_calls WHERE analysis_id=?',(job_id,))
            app.state.db.commit()

    def restart_analysis(job_id, request, action):
        with lock:
            row=app.state.db.execute('SELECT * FROM jobs WHERE id=? AND owner=?',(job_id,request.state.owner)).fetchone()
            if not row:raise HTTPException(404,'Анализ не найден.')
            if row['status'] in ('queued','running','done'):
                return {'id':job_id,'status':row['status']}
            if action=='resume' and row['retry_action']=='retry':
                raise HTTPException(409,'Этот шаг завершился отказом. Нужен явный повтор с новым запросом к модели.')
            if action=='retry' and row['retry_action']!='retry':
                raise HTTPException(409,'Сначала возобновите существующую задачу без нового запроса.')
            active=app.state.db.execute("SELECT COUNT(*) FROM jobs WHERE status IN ('queued','running')").fetchone()[0]
            if active>=2:raise HTTPException(429,'Дождитесь завершения текущих анализов.')
            payload=AnalysisRequest.model_validate_json(row['input'])
            if action=='retry' and row['failed_call_key']:
                app.state.db.execute('DELETE FROM model_calls WHERE analysis_id=? AND call_key=?',(job_id,row['failed_call_key']))
            app.state.db.execute("UPDATE jobs SET status='queued',error=NULL,retry_action=NULL,failed_call_key=NULL WHERE id=?",(job_id,))
            app.state.db.commit()
        app.state.pool.submit(work,job_id,payload)
        return {'id':job_id,'status':'queued'}

    @app.post('/api/analyses/{job_id}/resume', status_code=202)
    def resume_analysis(job_id: str, request: Request):
        return restart_analysis(job_id, request, 'resume')

    @app.post('/api/analyses/{job_id}/retry', status_code=202)
    def retry_analysis(job_id: str, request: Request):
        return restart_analysis(job_id, request, 'retry')

    dist = ROOT / "frontend/dist"
    if (dist / "assets").exists():
        app.mount("/assets", StaticFiles(directory=dist / "assets"), name="assets")

    @app.get("/")
    def index():
        if not (dist / "index.html").exists():
            raise HTTPException(503, "Сначала соберите интерфейс: npm run build в папке frontend.")
        return FileResponse(dist / "index.html")

    @app.get("/report-draft")
    def draft_report():
        path = ROOT / "reports/stage2-draft.html"
        if not path.exists():
            raise HTTPException(404, "Черновик отчёта ещё не сформирован.")
        return FileResponse(path)

    return app


app = create_app()
