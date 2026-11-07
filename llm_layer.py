"""Единый слой вызова LLM. Модель выбирается конфигурацией (.env / аргумент), логика не меняется.

Без внешних зависимостей: только стандартная библиотека (REST API Google AI Studio).
"""
import json
import logging
import os
import time
import urllib.error
import ssl
import urllib.request
from pathlib import Path

log = logging.getLogger("llm")
try:
    import certifi
    CTX = ssl.create_default_context(cafile=certifi.where())
except ImportError:  # macOS python.org: берём системные сертификаты
    CTX = ssl.create_default_context(cafile="/etc/ssl/cert.pem") if os.path.exists("/etc/ssl/cert.pem") else ssl.create_default_context()
API = "https://generativelanguage.googleapis.com/v1beta/models/{model}:generateContent"


class NoCredentialRedirect(urllib.request.HTTPRedirectHandler):
    """Provider endpoints are fixed; authenticated requests never follow redirects."""
    def redirect_request(self, req, fp, code, msg, headers, newurl):
        return None


def authenticated_urlopen(request, *, timeout):
    opener = urllib.request.build_opener(urllib.request.HTTPSHandler(context=CTX), NoCredentialRedirect())
    return opener.open(request, timeout=timeout)


def load_env(path: str = ".env") -> None:
    """Минимальный загрузчик .env (ключ не попадает в репозиторий)."""
    if not os.path.exists(path):
        return
    for line in Path(path).read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if line and not line.startswith("#") and "=" in line:
            k, v = line.split("=", 1)
            os.environ.setdefault(k.strip(), v.strip().strip('"').strip("'"))


def generate(prompt: str, model: str | None = None, retries: int = 2, timeout: int = 90) -> dict:
    """Возвращает {model, ok, text, latency_s, error, usage}. Ошибки логируются, не падает молча."""
    load_env()
    key = os.environ.get("GEMINI_API_KEY")
    model = model or os.environ.get("LLM_MODEL", "gemini-3.8-flash")
    if not key:
        return {"model": model, "ok": False, "text": "", "latency_s": 0, "error": "GEMINI_API_KEY не задан", "usage": {}}
    body = json.dumps({"contents": [{"parts": [{"text": prompt}]}]}).encode()
    req = urllib.request.Request(API.format(model=model), body,
                                 {"Content-Type": "application/json", "x-goog-api-key": key})
    err = ""
    for attempt in range(retries + 1):
        t0 = time.time()
        try:
            with authenticated_urlopen(req, timeout=timeout) as r:
                data = json.load(r)
            candidate = data["candidates"][0]
            if candidate.get('finishReason') not in (None, 'STOP'):
                err = 'Модель вернула незавершённый ответ'
                break
            parts = candidate["content"]["parts"]
            text = "".join(p.get("text", "") for p in parts if not p.get('thought'))
            return {"model": model, "ok": True, "text": text, "latency_s": round(time.time() - t0, 2),
                    "error": "", "usage": data.get("usageMetadata", {})}
        except urllib.error.HTTPError as e:
            err = f"HTTP {e.code}"
            log.error("%s attempt %d: %s", model, attempt, err)
            if e.code not in (429, 500, 503):
                break
        except Exception as e:  # сеть, разбор ответа
            err = f"Ошибка вызова модели ({type(e).__name__})"
            log.error("%s attempt %d: %s", model, attempt, err)
        time.sleep(2 * (attempt + 1))
    return {"model": model, "ok": False, "text": "", "latency_s": round(time.time() - t0, 2), "error": err, "usage": {}}
