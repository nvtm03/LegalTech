"""Provider adapters. Router credentials never leave this server-side module."""
from __future__ import annotations

import json
import os
import time
import hashlib
import urllib.error
import urllib.request
from urllib.parse import quote

from llm_layer import authenticated_urlopen, load_env


class ModelError(RuntimeError):
    """Safe, credential-free error for callers."""


def _request(url, key, body=None, timeout=30, google=False):
    headers = {"Content-Type": "application/json"}
    headers["x-goog-api-key" if google else "Authorization"] = key if google else f"Bearer {key}"
    req = urllib.request.Request(url, data=None if body is None else json.dumps(body).encode(), headers=headers)
    try:
        with authenticated_urlopen(req, timeout=timeout) as response:
            return json.load(response)
    except urllib.error.HTTPError as exc:
        # Do not expose remote bodies: they may contain prompts or credentials.
        codes = {401: "ключ не принят", 403: "модель недоступна", 413: "запрос слишком большой", 429: "достигнут лимит запросов"}
        raise ModelError(f"API: {codes.get(exc.code, 'ошибка сервиса')} (HTTP {exc.code})") from None
    except (urllib.error.URLError, TimeoutError, OSError, ValueError):
        raise ModelError("API не ответил корректно. Проверьте соединение и повторите позже.") from None


def generate_json(prompt, schema, *, provider=None, model=None, timeout=None, system="", checkpoint=None):
    load_env()
    provider = provider or os.getenv("LLM_PROVIDER", "router")
    model = model or os.getenv("LLM_MODEL", "gemini-3.1-flash-lite")
    timeout = timeout or float(os.getenv("LLM_TIMEOUT_SECONDS", "300"))
    if timeout <= 0:
        raise ModelError("Время ожидания должно быть положительным.")
    started = time.monotonic()
    config = {"responseMimeType": "application/json", "responseSchema": schema, "maxOutputTokens": 8192}
    contents = [{"role": "user", "parts": [{"text": prompt}]}]
    instruction = {"parts": [{"text": system}]} if system else None
    if provider == "router":
        key = os.getenv("ROUTER_API_KEY")
        if not key:
            raise ModelError("Настройте ROUTER_API_KEY в локальном .env.")
        # Fixed destination: a browser client cannot redirect credentials elsewhere.
        base = "https://router-ai-pe.ai360.group/api/v1/jobs"
        payload = {"model": model, "contents": contents, "config": config, "fallback": False}
        if instruction:
            payload["systemInstruction"] = instruction
        cache_key=hashlib.sha256(json.dumps({'provider':provider,**payload},sort_keys=True,ensure_ascii=False).encode()).hexdigest()
        job=checkpoint(cache_key) if checkpoint else None
        cache_hit=bool(job)
        if not job:
            job = _request(base, key, payload, timeout=min(30, timeout))
            if checkpoint:checkpoint(cache_key,job)
        job_id = job.get("id")
        if not isinstance(job_id, str) or not job_id.startswith("job_"):
            raise ModelError("Router не вернул идентификатор задачи.")
        while job.get("status") in ("queued", "running"):
            remaining = timeout - (time.monotonic() - started)
            if remaining <= 10:
                raise ModelError("Истекло время ожидания Router. Возобновите тот же анализ." if checkpoint else "Истекло время ожидания Router. Повторный запуск создаст новый запрос.")
            time.sleep(10)
            job = _request(f"{base}/{quote(job_id, safe='')}", key, timeout=min(30, remaining - 10))
            if checkpoint:checkpoint(cache_key,job)
        if job.get("status") != "done":
            raise ModelError("Router не выполнил задачу. Проверьте её статус в Monitoring.")
        result = job.get("result") or {}
        if result.get("finishReason") not in (None, "STOP"):
            raise ModelError("Модель вернула незавершённый ответ. Уменьшите размер документа.")
        raw = result.get("text", "")
        metadata = {"job_id": job_id, "usage": result.get("usage", {}), "served_by": job.get("fallback", {}).get("served_by", model),'resumed':cache_hit}
    elif provider == "google":
        key = os.getenv("GEMINI_API_KEY")
        if not key:
            raise ModelError("Настройте GEMINI_API_KEY в локальном .env.")
        payload = {"contents": contents, "generationConfig": config}
        if instruction:
            payload["systemInstruction"] = instruction
        result = _request(f"https://generativelanguage.googleapis.com/v1beta/models/{quote(model, safe='')}:generateContent", key, payload, timeout=timeout, google=True)
        candidates = result.get("candidates") or []
        if not candidates or candidates[0].get("finishReason") not in (None, "STOP"):
            raise ModelError("Google не вернул полный ответ.")
        raw = "".join(p.get("text", "") for p in candidates[0].get("content", {}).get("parts", []) if not p.get("thought"))
        metadata = {"usage": result.get("usageMetadata", {}), "served_by": model}
    else:
        raise ModelError("Неизвестный провайдер модели.")
    try:
        parsed = json.loads(raw)
    except (ValueError, TypeError):
        raise ModelError("Модель вернула ответ вне формата JSON.") from None
    return parsed, {"provider": provider, "model": model, "latency_s": round(time.monotonic() - started, 3), **metadata}
