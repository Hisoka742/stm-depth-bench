"""Анализ эксперимента с длиной контекста и положением цепочки (после score.py).

    python scripts/analyze_length.py data/length_bank

Для каждой модели: точность (среднее по глубинам, формула 2.3) в каждом из девяти условий
«длина × положение», точность по глубине для каждой длины и классы ошибок. Во всех условиях
одни и те же 120 вопросов, поэтому различия между условиями — внутри одних и тех же вопросов;
доверительные интервалы — бутстреп по сценариям. Результат: results/<набор>/length_analysis.md
и рисунок length.png.
"""
from __future__ import annotations

import glob
import json
import os
import random
import sys
from collections import Counter, defaultdict

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
LENGTHS = ["2k", "16k", "64k"]
POSITIONS = ["start", "middle", "end"]
POS_RU = {"start": "начало", "middle": "середина", "end": "конец"}


def load(path):
    with open(path, encoding="utf-8") as f:
        return [json.loads(x) for x in f if x.strip()]


def macro(rows):
    by = defaultdict(list)
    for r in rows:
        by[r["k"]].append(r["cls"] == "correct")
    return sum(sum(v) / len(v) for v in by.values()) / len(by) if by else None


def boot(rows, iters=2000, seed=0):
    """95 % интервал бутстрепом по сценариям."""
    by_s = defaultdict(list)
    for r in rows:
        by_s[r["sid"]].append(r)
    sids = sorted(by_s)
    rng = random.Random(seed)
    vals = []
    for _ in range(iters):
        sample = [r for s in (rng.choice(sids) for _ in sids) for r in by_s[s]]
        vals.append(macro(sample))
    vals.sort()
    return vals[int(0.025 * iters)], vals[int(0.975 * iters)]


def f2(x):
    return "—" if x is None else f"{x:.2f}".replace(".", ",")


def main(set_dir):
    name = os.path.basename(os.path.normpath(set_dir))
    rdir = os.path.join(ROOT, "results", name)
    models = {}
    for p in sorted(glob.glob(os.path.join(rdir, "*__scored.jsonl"))):
        base = os.path.basename(p)[: -len("__scored.jsonl")]
        if not base.startswith("mock__"):
            models[base.split("__", 1)[1]] = [r for r in load(p) if r["qtype"] == "depth"]
    L = [f"# Длина контекста и положение цепочки: {name}", "",
         "12 сценариев с n = 10, по одному вопросу на глубину (120 вопросов); в каждом условии одни и те же "
         "вопросы. Точность — среднее по глубинам (формула 2.3); в скобках — 95 % интервал бутстрепом по сценариям.", ""]
    for m, rows in models.items():
        for r in rows:
            r["L"], r["P"] = r["position"].split("@")[1], r["position"].split("@")[0]
        L += [f"## {m}", "", "| Положение \\ длина | " + " | ".join(LENGTHS) + " | Все длины |", "|---|---|---|---|---|"]
        for p in POSITIONS:
            cells = []
            for ln in LENGTHS:
                rr = [r for r in rows if r["L"] == ln and r["P"] == p]
                lo, hi = boot(rr)
                cells.append(f"{f2(macro(rr))} ({f2(lo)}–{f2(hi)})")
            cells.append(f2(macro([r for r in rows if r["P"] == p])))
            L.append(f"| {POS_RU[p]} | " + " | ".join(cells) + " |")
        L.append("| все положения | " + " | ".join(f2(macro([r for r in rows if r["L"] == ln])) for ln in LENGTHS)
                 + f" | {f2(macro(rows))} |")
        L += ["", "Точность по глубине k (все положения):", "",
              "| Длина | " + " | ".join(f"k = {k}" for k in range(10)) + " |", "|---|" + "---|" * 10]
        for ln in LENGTHS:
            rr = [r for r in rows if r["L"] == ln]
            L.append(f"| {ln} | " + " | ".join(
                f2(sum(r["cls"] == "correct" for r in rr if r["k"] == k) / max(1, sum(1 for r in rr if r["k"] == k)))
                for k in range(10)) + " |")
        L += ["", "Классы ответов по длине (доли):", "", "| Длина | верно | более поздняя | более ранняя | отказ | прочее |",
              "|---|---|---|---|---|---|"]
        for ln in LENGTHS:
            rr = [r for r in rows if r["L"] == ln]
            c = Counter(r["cls"] for r in rr)
            other = len(rr) - c["correct"] - c["later_version"] - c["earlier_version"] - c["refusal"]
            L.append(f"| {ln} | {f2(c['correct'] / len(rr))} | {f2(c['later_version'] / len(rr))} | "
                     f"{f2(c['earlier_version'] / len(rr))} | {f2(c['refusal'] / len(rr))} | {f2(other / len(rr))} |")
        L.append("")
    try:
        import matplotlib
        matplotlib.use("Agg")
        import matplotlib.pyplot as plt
        fig, axes = plt.subplots(1, len(models), figsize=(4.2 * len(models), 3.6), sharey=True)
        axes = axes if len(models) > 1 else [axes]
        for ax, (m, rows) in zip(axes, models.items()):
            for p in POSITIONS:
                ax.plot(LENGTHS, [macro([r for r in rows if r["L"] == ln and r["P"] == p]) for ln in LENGTHS],
                        marker="o", label=POS_RU[p])
            ax.set_title(m, fontsize=9)
            ax.set_xlabel("длина входа, тыс. токенов")
            ax.set_ylim(0, 1.02)
            ax.grid(alpha=0.3)
        axes[0].set_ylabel("точность")
        axes[0].legend(title="цепочка", fontsize=8)
        fig.tight_layout()
        fig.savefig(os.path.join(rdir, "length.png"), dpi=150)
        L += ["![Точность по длине и положению](length.png)"]
    except ImportError:
        pass
    text = "\n".join(L) + "\n"
    with open(os.path.join(rdir, "length_analysis.md"), "w", encoding="utf-8") as fh:
        fh.write(text)
    print(text)


if __name__ == "__main__":
    main(sys.argv[1])
