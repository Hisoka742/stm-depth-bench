"""Сводная таблица по всем моделям набора (после score.py).

    python scripts/compare.py data/pilot

Читает results/<набор>/*__summary.json и файлы ответов, добавляет строку с нижней
границей (лучшая поверхностная эвристика по каждому способу задания глубины) и
сохраняет results/<набор>/comparison.md.
"""
from __future__ import annotations

import glob
import json
import os
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)
from scripts.bounds import compute, load  # noqa: E402
from stmbench.solvers import VARIANTS, macro  # noqa: E402

SIGMAS = ["direct", "ordinal", "relative", "event_value", "event_desc"]
SIG_RU = {"direct": "прямой", "ordinal": "порядк.", "relative": "относит.", "event_value": "событие: знач.",
          "event_desc": "событие: опис."}


def f(x):
    return "—" if x is None else f"{x:.2f}".replace(".", ",")


def main(set_dir):
    name = os.path.basename(os.path.normpath(set_dir))
    rdir = os.path.join(ROOT, "results", name)
    scen = load(set_dir)
    ns = sorted({s["n"] for s in scen})
    _, heur = compute(scen)
    bound = {sg: max(macro(heur[v][sg]) or 0 for v in VARIANTS) for sg in SIGMAS + ["ALL"]}
    bound_n = {n: max(macro(heur[v][("ALL", n)]) or 0 for v in VARIANTS) for n in ns}

    rows = []
    for p in sorted(glob.glob(os.path.join(rdir, "*__summary.json"))):
        base = os.path.basename(p)[: -len("__summary.json")]
        if base.startswith(("mock__", "judge__")):
            continue
        with open(p, encoding="utf-8") as fh:
            s = json.load(fh)
        cost = 0.0
        resp = os.path.join(rdir, base + ".jsonl")
        if os.path.exists(resp):
            with open(resp, encoding="utf-8") as fh:
                for line in fh:
                    r = json.loads(line)
                    if r.get("error") is None and r.get("usage"):
                        cost += r["usage"].get("cost") or 0
        rows.append((base.replace("__", "/"), s, cost))
    rows.sort(key=lambda r: -(r[1].get("log", {}).get("acc_macro") or 0))

    L = [f"# Результаты моделей: {name}", "",
         "Точность — макросреднее по глубинам k (формула 2.2), формат «лог», три положения цепочки.", "",
         "| Модель | Все | " + " | ".join(f"n = {n}" for n in ns) + " | " + " | ".join(SIG_RU[s] for s in SIGMAS)
         + " | Факты | Ложн. предпосылка | Отказ (забыть) | Утечки | Судья | $ |",
         "|---|" + "---|" * (1 + len(ns) + len(SIGMAS) + 6)]
    for mid, s, cost in rows:
        lg, fc = s.get("log", {}), s.get("facts", {})
        fp, fg = s.get("false_premise", {}), s.get("forgotten", {})
        L.append(f"| {mid} | {f(lg.get('acc_macro'))} | "
                 + " | ".join(f(lg.get("by_n", {}).get(str(n))) for n in ns) + " | "
                 + " | ".join(f(lg.get("by_sigma", {}).get(sg)) for sg in SIGMAS)
                 + f" | {f(fc.get('acc_macro'))} | {f(fp.get('correct'))} | {f(fg.get('refusal'))}"
                 + f" | {f(s.get('leak_rate_all_answers'))} | {f(s.get('share_judge'))} | {cost:.3f} |")
    L.append(f"| *нижняя граница (эвристика)* | {f(bound['ALL'])} | "
             + " | ".join(f(bound_n[n]) for n in ns) + " | " + " | ".join(f(bound[sg]) for sg in SIGMAS)
             + " | | | | | | |")
    L += ["", "Факты — формат «список фактов»; ложн. предпосылка — доля верных ответов на вопросы с ложной "
          "предпосылкой; отказ — доля отказов на вопросы о значении, которое просили не называть; утечки — доля "
          "ответов, где появилось забытое значение, среди всех ответов по сценариям с просьбой забыть; судья — доля "
          "ответов, классифицированных LLM-судьёй; $ — фактическая стоимость ответов модели по данным OpenRouter."]
    text = "\n".join(L) + "\n"
    with open(os.path.join(rdir, "comparison.md"), "w", encoding="utf-8") as fh:
        fh.write(text)
    print(text)


if __name__ == "__main__":
    main(sys.argv[1])
