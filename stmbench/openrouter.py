"""Минимальный клиент OpenRouter (совместимый с OpenAI Chat Completions API).

Ключ берётся из переменной окружения OPENROUTER_API_KEY и никуда не записывается.
"""
from __future__ import annotations

import json
import os
import time
import urllib.error
import urllib.request

URL = "https://openrouter.ai/api/v1/chat/completions"
# Отключение рассуждения (унифицированный параметр OpenRouter). Без него модели с
# рассуждением по умолчанию тратят весь лимит max_tokens на рассуждение и не отвечают.
NO_REASONING = {"reasoning": {"effort": "none"}}


class OpenRouterError(RuntimeError):
    pass


def chat(model: str, messages: list[dict], temperature: float = 0.0, max_tokens: int = 512,
         extra: dict | None = None, retries: int = 6, timeout: int = 120) -> dict:
    key = os.environ.get("OPENROUTER_API_KEY")
    if not key:
        raise OpenRouterError("не задана переменная окружения OPENROUTER_API_KEY")
    body = {"model": model, "messages": messages, "temperature": temperature, "max_tokens": max_tokens,
            "usage": {"include": True}}  # в usage возвращается стоимость запроса (поле cost)
    if extra:
        body.update(extra)
    data = json.dumps(body).encode("utf-8")
    delay = 2.0
    last = None
    for attempt in range(retries):
        req = urllib.request.Request(URL, data=data, method="POST", headers={
            "Authorization": f"Bearer {key}", "Content-Type": "application/json"})
        t0 = time.time()
        try:
            with urllib.request.urlopen(req, timeout=timeout) as r:
                resp = json.loads(r.read().decode("utf-8"))
            if "error" in resp:
                raise OpenRouterError(str(resp["error"]))
            ch = resp["choices"][0]
            return dict(content=(ch["message"].get("content") or "").strip(),
                        finish_reason=ch.get("finish_reason"), usage=resp.get("usage"),
                        provider=resp.get("provider"), model_returned=resp.get("model"),
                        latency=round(time.time() - t0, 2))
        except urllib.error.HTTPError as e:
            last = f"HTTP {e.code}: {e.read()[:300]!r}"
            if e.code not in (408, 429, 500, 502, 503, 504):
                raise OpenRouterError(last)
        except (urllib.error.URLError, TimeoutError, OpenRouterError, KeyError) as e:
            last = repr(e)
        time.sleep(delay)
        delay = min(delay * 2, 60)
    raise OpenRouterError(f"запрос не выполнен после {retries} попыток: {last}")


def key_info(timeout: int = 30) -> dict:
    """Расход и остаток по ключу (сам ключ не выводится)."""
    key = os.environ.get("OPENROUTER_API_KEY")
    if not key:
        raise OpenRouterError("не задана переменная окружения OPENROUTER_API_KEY")
    req = urllib.request.Request("https://openrouter.ai/api/v1/key", headers={"Authorization": f"Bearer {key}"})
    with urllib.request.urlopen(req, timeout=timeout) as r:
        return json.loads(r.read().decode("utf-8"))["data"]
