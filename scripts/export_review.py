"""Выгрузка пилотного набора для ручной проверки разметки (п. 2.3 ВКР).

    python scripts/export_review.py data/pilot

Создаёт data/<набор>/review/dialogs.md (все диалоги с размеченными записями версий)
и review.csv (по строке на вопрос) с пустыми колонками для проверяющего:
«эталон однозначен», «формулировка естественна (1–3)», «комментарий».
"""
from __future__ import annotations

import csv
import json
import os
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)
from stmbench.render import dialog_turns  # noqa: E402

SIG = {"direct": "прямой", "ordinal": "порядковый", "relative": "относительный",
       "event_value": "через следующее значение", "event_desc": "через описание события",
       "false_premise": "ложная предпосылка"}
CH = {"first": "первое", "explicit": "явная замена", "implicit": "неявное", "correction": "исправление"}


def main(set_dir):
    scen = [json.loads(x) for x in open(os.path.join(set_dir, "scenarios.jsonl"), encoding="utf-8")]
    out = os.path.join(set_dir, "review")
    os.makedirs(out, exist_ok=True)
    md = []
    rows = []
    for s in scen:
        p = s["positions"][0]
        turns, meta = dialog_turns(s, p)
        rec = {v: k for k, v in meta["record_turn"].items()}
        md.append(f"## {s['id']} — {s['domain']}, n = {s['n']}, m = {s['m']}, доп. событие: {s['extra']}, позиция: {p}\n")
        md.append("Цепочка: " + " → ".join(f"v{j} {c['value']} ({CH[c['change']]})" for j, c in enumerate(s["chain"], 1)) + "\n")
        for i, (r, t) in enumerate(turns):
            mark = f" **[v{rec[i]}]**" if i in rec else ""
            md.append(f"{i}. {'П' if r == 'u' else 'А'}:{mark} {t}")
        md.append("\nВопросы:\n")
        for q in s["questions"]:
            gold = q["gold"] if q["gold"] is not None else "⊥ (отказ)"
            md.append(f"- {q['qid']} [{SIG[q['sigma']]}, k = {q['k']}] {q['text']} → **{gold}**")
            rows.append([q["qid"], s["domain"], s["n"], s["m"], s["extra"], p, q["k"], SIG[q["sigma"]],
                         q.get("direction") or "", q["text"], gold, "", "", ""])
        md.append("\n---\n")
    with open(os.path.join(out, "dialogs.md"), "w", encoding="utf-8") as f:
        f.write("\n".join(md))
    with open(os.path.join(out, "review.csv"), "w", encoding="utf-8-sig", newline="") as f:
        w = csv.writer(f, delimiter=";")
        w.writerow(["qid", "домен", "n", "m", "доп. событие", "позиция", "k", "способ", "направление",
                    "вопрос", "эталон", "эталон однозначен (да/нет)", "естественность (1–3)", "комментарий"])
        w.writerows(rows)
    print(f"сценариев: {len(scen)}, вопросов: {len(rows)} -> {out}")


if __name__ == "__main__":
    main(sys.argv[1])
