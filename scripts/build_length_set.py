"""Набор для эксперимента с длиной контекста и положением цепочки.

    python scripts/build_length_set.py

12 сценариев с n = 10 (шесть областей × m ∈ {0, 2}, без дополнительных событий), к каждому —
по одному вопросу на глубину k = 0, …, 9 (способ задания глубины чередуется: порядковый, через
следующее значение, через описание события). Каждый вопрос подаётся в девяти условиях:
длина входа около 2, 16 и 64 тыс. токенов × цепочка в начале, середине или конце диалога.
Во всех условиях сценарии, вопросы и сама область цепочки одинаковы; меняются только длина
постороннего наполнителя и его деление на часть до цепочки и после неё. При 2 тыс. токенов
наполнитель — обычные шесть посторонних обменов сценария; при 16 и 64 тыс. — обмены из
data/filler_bank.jsonl, взятые по порядку (наполнитель для 16 тыс. — начало наполнителя для 64 тыс.).

Результат: data/length_bank/scenarios.jsonl, items.jsonl, report.txt.
"""
from __future__ import annotations

import json
import os
import sys
from collections import defaultdict

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)
from scripts.estimate import ntok  # noqa: E402
from stmbench.generator import generate_scenario  # noqa: E402
from stmbench.render import messages_log  # noqa: E402
from stmbench.validate import validate  # noqa: E402

DOMAINS = ["cards", "payments", "transfers", "notifications", "calls", "autopay"]
LENGTHS = {"2k": None, "16k": 16000, "64k": 64000}
POSITIONS = ["start", "middle", "end"]
SIGMAS = ["ordinal", "event_value", "event_desc"]
SEED = 41


def pick_questions(s, idx):
    """Один вопрос на каждую глубину; способ задания глубины чередуется."""
    out = []
    for k in range(s["n"]):
        if k == 0:
            cand = [q for q in s["questions"] if q["k"] == 0 and q["sigma"] == "direct"]
        else:
            sg = SIGMAS[(k + idx) % 3]
            cand = [q for q in s["questions"] if q["k"] == k and q["sigma"] == sg]
        out.append(cand[0])
    return out


def main():
    out_dir = os.path.join(ROOT, "data", "length_bank")
    os.makedirs(out_dir, exist_ok=True)
    with open(os.path.join(ROOT, "data", "filler_bank.jsonl"), encoding="utf-8") as f:
        bank = [json.loads(x) for x in f if x.strip()]
    bank_blocks = [dict(kind="filler", turns=[("u", x["q"]), ("a", x["a"])]) for x in bank]
    bank_tok = [ntok([{"content": x["q"]}, {"content": x["a"]}]) for x in bank]

    scen, report = [], []
    i = 0
    for m in (0, 2):
        for dom in DOMAINS:
            i += 1
            sid = f"L{i:03d}"
            for attempt in range(50):
                s = generate_scenario(sid, dom, 10, m, "none", SEED * 100000 + i + attempt * 7919)
                errs = validate(s)
                if not errs:
                    break
                report.append(f"{sid} попытка {attempt}: " + "; ".join(errs))
            s["questions"] = pick_questions(s, i)
            s["block"] = "length"
            scen.append(s)

    items, stats = [], defaultdict(list)
    for s in scen:
        q0 = s["questions"][0]
        base = ntok(messages_log(s, q0, "middle", pos_filler=[]))
        for L, target in LENGTHS.items():
            if target is None:
                filler = None
            else:
                need, acc, filler = target - base, 0, []
                for b, t in zip(bank_blocks, bank_tok):
                    if acc >= need:
                        break
                    filler.append(b)
                    acc += t
                if acc < need:
                    raise RuntimeError("не хватает наполнителя")
            for p in POSITIONS:
                for q in s["questions"]:
                    msgs = messages_log(s, q, p, pos_filler=filler)
                    stats[L].append(ntok(msgs))
                    items.append(dict(item_id=f"{q['qid']}-log-{p}-{L}", sid=s["id"], qid=q["qid"], fmt="log",
                                      position=f"{p}@{L}", messages=msgs, dist_turns=None))
    with open(os.path.join(out_dir, "scenarios.jsonl"), "w", encoding="utf-8") as f:
        for s in scen:
            f.write(json.dumps(s, ensure_ascii=False) + "\n")
    with open(os.path.join(out_dir, "items.jsonl"), "w", encoding="utf-8") as f:
        for it in items:
            f.write(json.dumps(it, ensure_ascii=False) + "\n")
    lines = [f"сценариев: {len(scen)}, вопросов: {sum(len(s['questions']) for s in scen)}, входов: {len(items)}"]
    for L, v in stats.items():
        lines.append(f"{L}: входов {len(v)}, токенов во входе — мин. {min(v)}, среднее {sum(v) / len(v):.0f}, "
                     f"макс. {max(v)}; всего {sum(v) / 1e6:.2f} млн")
    text = "\n".join(lines + report) + "\n"
    with open(os.path.join(out_dir, "report.txt"), "w", encoding="utf-8") as f:
        f.write(text)
    print(text)


if __name__ == "__main__":
    main()
