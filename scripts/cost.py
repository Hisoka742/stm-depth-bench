"""Оценка стоимости запуска моделей по текущим ценам OpenRouter.

    python scripts/cost.py data/pilot data/main --models configs/models.yaml
    python scripts/cost.py data/main --reasoning-tokens 300     # если модели рассуждают

Цены берутся из открытого списка моделей OpenRouter (ключ не нужен). Входные токены
считаются токенизатором o200k_base, поэтому оценка ориентировочная. Выводятся две
суммы: без кэширования (верхняя граница) и с кэшированием общего начала входа —
вопросы одного сценария в одном положении различаются только последней репликой,
и провайдеры с автоматическим кэшем берут за повторное начало меньшую цену.
"""
from __future__ import annotations

import argparse
import json
import os
import sys
import time
import urllib.request
from collections import defaultdict

import yaml

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)
from scripts.estimate import ntok  # noqa: E402

MODELS_URL = "https://openrouter.ai/api/v1/models"


def prices() -> dict:
    req = urllib.request.Request(MODELS_URL, headers={"User-Agent": "stm-depth-bench"})
    with urllib.request.urlopen(req, timeout=60) as r:
        data = json.loads(r.read().decode("utf-8"))["data"]
    out = {}
    for m in data:
        p = m.get("pricing", {})
        try:
            inp, outp = float(p["prompt"]) * 1e6, float(p["completion"]) * 1e6
        except (KeyError, TypeError, ValueError):
            continue
        cache = p.get("input_cache_read")
        out[m["id"]] = dict(inp=inp, out=outp, cache=float(cache) * 1e6 if cache else inp)
    return out


def set_tokens(set_dir: str) -> dict:
    """Входные токены набора: всего и доля, которая может быть взята из кэша."""
    with open(os.path.join(set_dir, "items.jsonl"), encoding="utf-8") as f:
        items = [json.loads(x) for x in f if x.strip()]
    total, cacheable = 0, 0
    groups = defaultdict(int)
    for it in items:
        t = ntok(it["messages"])
        total += t
        key = (it["sid"], it["fmt"], it["position"])
        groups[key] += 1
        if groups[key] > 1:  # общее начало уже передавалось в этом сценарии
            cacheable += ntok(it["messages"][:-1])
    return dict(calls=len(items), total=total, cacheable=cacheable)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("sets", nargs="+")
    ap.add_argument("--models", default=os.path.join(ROOT, "configs", "models.yaml"))
    ap.add_argument("--out-tokens", type=int, default=20, help="токенов в ответе без рассуждения")
    ap.add_argument("--reasoning-tokens", type=int, default=0,
                    help="токенов рассуждения на вызов для моделей с extra.reasoning")
    ap.add_argument("--judge-share", type=float, default=0.15)
    ap.add_argument("--judge-tokens", type=int, default=450, help="входных токенов в запросе судьи")
    args = ap.parse_args()

    with open(args.models, encoding="utf-8") as f:
        cfg = yaml.safe_load(f)
    pr = prices()
    sets = {os.path.basename(os.path.normpath(s)): set_tokens(s) for s in args.sets}
    print(f"цены OpenRouter на {time.strftime('%d.%m.%Y')}, $ за 1 млн токенов (вход / выход / кэш)")
    for name, st in sets.items():
        print(f"{name}: {st['calls']} вызовов на модель, {st['total'] / 1e6:.2f} млн входных токенов, "
              f"из них {st['cacheable'] / st['total']:.0%} — повторное начало входа")
    head = "".join(f"{n:>18s}" for n in sets)
    print(f"\n{'модель':40s}{'цены':>22s}{head}")
    grand = defaultdict(lambda: [0.0, 0.0])
    for m in cfg["models"]:
        p = pr.get(m["id"])
        if p is None:
            print(f"{m['id']:40s}  нет в списке OpenRouter")
            continue
        out_t = args.out_tokens + (args.reasoning_tokens if ((m.get("extra") or {}).get("reasoning") or {}).get("effort", "none") != "none" else 0)
        cells = []
        for name, st in sets.items():
            out_cost = st["calls"] * out_t * p["out"] / 1e6
            hi = st["total"] * p["inp"] / 1e6 + out_cost
            lo = ((st["total"] - st["cacheable"]) * p["inp"] + st["cacheable"] * p["cache"]) / 1e6 + out_cost
            grand[name][0] += lo
            grand[name][1] += hi
            cells.append(f"{lo:.2f}–{hi:.2f} $")
        price = f"{p['inp']:.3g}/{p['out']:.3g}/{p['cache']:.3g}"
        print(f"{m['id']:40s}{price:>22s}" + "".join(f"{c:>18s}" for c in cells))
    j = cfg.get("judge")
    if j and j["id"] in pr:
        p = pr[j["id"]]
        cells = []
        for name, st in sets.items():
            n_calls = st["calls"] * len(cfg["models"]) * args.judge_share
            c = n_calls * (args.judge_tokens * p["inp"] + 5 * p["out"]) / 1e6
            grand[name][0] += c
            grand[name][1] += c
            cells.append(f"{c:.2f} $")
        print(f"{'судья: ' + j['id']:40s}{'':>22s}" + "".join(f"{c:>18s}" for c in cells))
    print(f"{'ИТОГО':40s}{'':>22s}" + "".join(f"{grand[n][0]:.2f}–{grand[n][1]:.2f} $".rjust(18) for n in sets))


if __name__ == "__main__":
    main()
