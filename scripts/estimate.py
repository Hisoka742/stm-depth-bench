"""Оценка объёма набора и числа вызовов моделей (п. 2.2 ВКР).

    python scripts/estimate.py data/main --models 6 --judge-share 0.15

Число токенов считается токенизатором o200k_base (tiktoken), если он установлен;
у других моделей токенизация отличается, поэтому это ориентировочная оценка.
"""
from __future__ import annotations

import argparse
import json
import os
from collections import Counter, defaultdict

try:
    import tiktoken
    ENC = tiktoken.get_encoding("o200k_base")
except Exception:  # noqa: BLE001
    ENC = None


def ntok(msgs) -> int:
    text = "\n".join(m["content"] for m in msgs)
    return len(ENC.encode(text)) + 4 * len(msgs) if ENC else int(len(text) / 3.2)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("set_dir")
    ap.add_argument("--models", type=int, default=6)
    ap.add_argument("--judge-share", type=float, default=0.15)
    args = ap.parse_args()
    scen = [json.loads(x) for x in open(os.path.join(args.set_dir, "scenarios.jsonl"), encoding="utf-8")]
    items = [json.loads(x) for x in open(os.path.join(args.set_dir, "items.jsonl"), encoding="utf-8")]
    by_n = Counter(s["n"] for s in scen)
    q_by_n = defaultdict(int)
    for s in scen:
        q_by_n[s["n"]] += len(s["questions"])
    toks = [ntok(it["messages"]) for it in items]
    tok_by_fmt = defaultdict(list)
    for it, t in zip(items, toks):
        tok_by_fmt[it["fmt"]].append(t)
    calls = len(items)
    total_tok = sum(toks)
    print(f"сценариев: {len(scen)} (по n: {dict(sorted(by_n.items()))})")
    print(f"вопросов: {sum(len(s['questions']) for s in scen)} (по n: {dict(sorted(q_by_n.items()))})")
    print(f"входов на одну модель: {calls} (лог: {len(tok_by_fmt['log'])}, факты: {len(tok_by_fmt['facts'])})")
    for f, ts in tok_by_fmt.items():
        ts = sorted(ts)
        print(f"  токенов во входе [{f}]: среднее {sum(ts) / len(ts):.0f}, медиана {ts[len(ts) // 2]}, макс. {ts[-1]}")
    print(f"входных токенов на одну модель: {total_tok / 1e6:.2f} млн")
    print(f"на {args.models} моделей: {calls * args.models} вызовов, {total_tok * args.models / 1e6:.1f} млн токенов")
    print(f"вызовов судьи (при доле {args.judge_share:.0%}): ~{int(calls * args.models * args.judge_share)}")


if __name__ == "__main__":
    main()
