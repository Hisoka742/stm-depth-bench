"""Нижние границы точности на готовом наборе (п. 2.1.4, 2.3 ВКР).

    python scripts/bounds.py data/pilot

Печатает и сохраняет в bounds.md: точность стратегий с фиксированной позицией по длинам
цепочки и точность поверхностных эвристик по способам задания глубины (лучший вариант
и все варианты). Точность — среднее по глубинам k долей верных ответов.
"""
from __future__ import annotations

import json
import os
import sys
from collections import defaultdict

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from stmbench.solvers import FIXED, VARIANTS, heuristic_answer, macro  # noqa: E402
from stmbench.render import dialog_turns  # noqa: E402
from stmbench.scoring import value_in  # noqa: E402

SIGMA_RU = {"direct": "прямой (k = 0)", "ordinal": "порядковый", "relative": "относительный",
            "event_value": "через событие: следующее значение", "event_desc": "через событие: описание изменения",
            "ALL": "все вопросы глубины"}
VAR_RU = {"user": "реплики пользователя", "all": "все реплики", "none": "без фильтра",
          "entity": "ходы с названием сущности", "slot": "ходы с названием слота",
          "first": "порядок первых упоминаний", "last": "порядок последних упоминаний"}


def load(path):
    with open(os.path.join(path, "scenarios.jsonl"), encoding="utf-8") as f:
        return [json.loads(x) for x in f]


def compute(scen):
    fixed = defaultdict(lambda: defaultdict(list))
    heur = defaultdict(lambda: defaultdict(list))
    for s in scen:
        n = s["n"]
        for p in s.get("positions", ["end"]):
            turns, _ = dialog_turns(s, p)
            for q in s["questions"]:
                if q["qtype"] != "depth":
                    continue
                for name, f in FIXED.items():
                    ok = f(q, n) == q["gold_version"]
                    fixed[name][n].append((n, q["k"], ok))
                for var in VARIANTS:
                    a = heuristic_answer(s, q, turns, var)
                    ok = a is not None and value_in(a, q["gold"], s["vtype"])
                    for key in (q["sigma"], "ALL"):
                        heur[var][key].append((n, q["k"], ok))
                        heur[var][(key, n)].append((n, q["k"], ok))
    return fixed, heur


def main(path):
    scen = load(path)
    fixed, heur = compute(scen)
    ns = sorted({s["n"] for s in scen})
    lines = ["# Нижние границы точности", "", f"Набор: {path}, сценариев: {len(scen)}", "",
             "## Стратегии с фиксированной позицией (по длине цепочки)", "",
             "| Стратегия | " + " | ".join(f"n = {n}" for n in ns) + " |",
             "|---|" + "---|" * len(ns)]
    for name in FIXED:
        lines.append(f"| {name} | " + " | ".join(f"{macro(fixed[name][n]):.3f}" for n in ns) + " |")
    lines += ["", "## Поверхностные эвристики: лучший вариант по способу задания глубины", "",
              "| Способ | Лучшая точность | " + " | ".join(f"n = {n}" for n in ns) + " | Вариант |",
              "|---|---|" + "---|" * len(ns) + "---|"]
    best_rows = {}
    for sig in ["direct", "ordinal", "relative", "event_value", "event_desc", "ALL"]:
        best = max(VARIANTS, key=lambda v: macro(heur[v][sig]) or 0)
        b = macro(heur[best][sig])
        per_n = [macro(heur[best][(sig, n)]) for n in ns]
        best_rows[sig] = (b, best)
        lines.append(f"| {SIGMA_RU[sig]} | {b:.3f} | " + " | ".join("—" if x is None else f"{x:.3f}" for x in per_n)
                     + f" | {', '.join(VAR_RU[x] for x in best)} |")
    lines += ["", "## Все варианты эвристики", "",
              "| Вариант | " + " | ".join(SIGMA_RU[s] for s in ["direct", "ordinal", "relative", "event_value", "event_desc", "ALL"]) + " |",
              "|---|" + "---|" * 6]
    for v in VARIANTS:
        lines.append(f"| {' / '.join(VAR_RU[x] for x in v)} | " +
                     " | ".join(f"{macro(heur[v][s]):.3f}" for s in ["direct", "ordinal", "relative", "event_value", "event_desc", "ALL"]) + " |")
    text = "\n".join(lines) + "\n"
    with open(os.path.join(path, "bounds.md"), "w", encoding="utf-8") as f:
        f.write(text)
    print(text)


if __name__ == "__main__":
    main(sys.argv[1])
