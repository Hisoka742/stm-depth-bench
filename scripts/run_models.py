"""Запуск моделей на наборе через OpenRouter.

    set OPENROUTER_API_KEY=...            (PowerShell: $env:OPENROUTER_API_KEY="...")
    python scripts/run_models.py data/pilot --models configs/models.yaml
    python scripts/run_models.py data/pilot --mock oracle      # проверка конвейера без API
    python scripts/run_models.py data/pilot --mock heuristic

Ответы дописываются в results/<набор>/<модель>.jsonl; уже полученные ответы не
запрашиваются повторно, поэтому прерванный запуск можно продолжить той же командой.
Параметры декодирования: temperature = 0, max_tokens из конфигурации модели.
"""
from __future__ import annotations

import argparse
import json
import os
import sys
import threading
import time
from concurrent.futures import ThreadPoolExecutor, as_completed

import yaml

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)
from stmbench.openrouter import chat  # noqa: E402
from stmbench.render import dialog_turns  # noqa: E402
from stmbench.solvers import heuristic_answer  # noqa: E402


def load_jsonl(path):
    if not os.path.exists(path):
        return []
    with open(path, encoding="utf-8") as f:
        return [json.loads(x) for x in f if x.strip()]


def slug(model_id: str) -> str:
    return model_id.replace("/", "__").replace(":", "_")


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("set_dir")
    ap.add_argument("--models", default=os.path.join(ROOT, "configs", "models.yaml"))
    ap.add_argument("--only", help="идентификатор одной модели из конфигурации")
    ap.add_argument("--fmt", choices=["log", "facts", "all"], default="all")
    ap.add_argument("--limit", type=int, default=0, help="не более N входов (для пробного запуска)")
    ap.add_argument("--workers", type=int, default=6)
    ap.add_argument("--mock", choices=["oracle", "heuristic"], help="ответы без обращения к API")
    args = ap.parse_args()

    set_name = os.path.basename(os.path.normpath(args.set_dir))
    items = load_jsonl(os.path.join(args.set_dir, "items.jsonl"))
    if args.fmt != "all":
        items = [it for it in items if it["fmt"] == args.fmt]
    if args.limit:
        items = items[:args.limit]
    scen = {s["id"]: s for s in load_jsonl(os.path.join(args.set_dir, "scenarios.jsonl"))}
    qmap = {q["qid"]: (s, q) for s in scen.values() for q in s["questions"]}

    if args.mock:
        models = [dict(id=f"mock/{args.mock}")]
    else:
        with open(args.models, encoding="utf-8") as f:
            models = yaml.safe_load(f)["models"]
        if args.only:
            models = [m for m in models if m["id"] == args.only]

    out_dir = os.path.join(ROOT, "results", set_name)
    os.makedirs(out_dir, exist_ok=True)
    for m in models:
        path = os.path.join(out_dir, slug(m["id"]) + ".jsonl")
        done = {r["item_id"] for r in load_jsonl(path) if r.get("error") is None}
        todo = [it for it in items if it["item_id"] not in done]
        print(f"{m['id']}: уже есть {len(done)}, осталось {len(todo)}")
        lock = threading.Lock()
        fout = open(path, "a", encoding="utf-8")

        def work(it):
            s, q = qmap[it["qid"]]
            rec = dict(item_id=it["item_id"], qid=it["qid"], model=m["id"], fmt=it["fmt"],
                       position=it["position"], time=time.strftime("%Y-%m-%dT%H:%M:%S"))
            try:
                if args.mock == "oracle":
                    rec["response"] = q["gold"] if q["gold"] is not None else "нет данных"
                elif args.mock == "heuristic":
                    turns, _ = dialog_turns(s, it["position"] or "end")
                    rec["response"] = heuristic_answer(s, q, turns, ("all", "entity", "first")) or "не знаю"
                else:
                    r = chat(m["id"], it["messages"], temperature=0.0, max_tokens=m.get("max_tokens", 512),
                             extra=m.get("extra"))
                    rec.update(response=r["content"], finish_reason=r["finish_reason"], usage=r["usage"],
                               provider=r["provider"], model_returned=r["model_returned"], latency=r["latency"])
                rec["error"] = None
            except Exception as e:  # ошибка записывается, вход будет повторён при следующем запуске
                rec["error"] = repr(e)
            with lock:
                fout.write(json.dumps(rec, ensure_ascii=False) + "\n")
                fout.flush()
            return rec

        n_err = 0
        with ThreadPoolExecutor(max_workers=1 if args.mock else args.workers) as ex:
            futs = [ex.submit(work, it) for it in todo]
            for i, f in enumerate(as_completed(futs), 1):
                if f.result()["error"]:
                    n_err += 1
                if i % 100 == 0:
                    print(f"  {i}/{len(todo)}, ошибок: {n_err}")
        fout.close()
        print(f"  готово, ошибок: {n_err}")


if __name__ == "__main__":
    main()
