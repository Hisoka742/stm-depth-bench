"""Анализ по глубине и номеру версии (после score.py).

    python scripts/analyze.py data/pilot_bank

Читает results/<набор>/*__scored.jsonl и строит results/<набор>/analysis.md и рисунки:
  - точность по глубине k для каждой модели, отдельно для каждой длины цепочки n;
  - точность по номеру версии j = n − k (первая версия цепочки — j = 1);
  - влияние n при фиксированной глубине (k = 0, 1, 2): сравниваются одинаковые глубины,
    а не средние по разным наборам глубин;
  - сравнение форматов «лог» и «список фактов» на одних и тех же вопросах;
  - распределение ошибок по классам.
Доля верных ответов в клетке приводится вместе с числом вопросов в ней.
"""
from __future__ import annotations

import glob
import json
import os
import sys
from collections import Counter, defaultdict

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))

CLS_RU = {"correct": "верно", "later_version": "более поздняя версия", "earlier_version": "более ранняя версия",
          "refusal": "отказ", "absent_value": "значения нет во входе", "rejected_value": "отклонённое значение",
          "other_slot": "значение другого слота", "unresolved": "не определено", "leak": "утечка",
          "accepted_premise": "принята ложная предпосылка"}


def load(path):
    with open(path, encoding="utf-8") as f:
        return [json.loads(x) for x in f if x.strip()]


def f2(x):
    return "—" if x is None else f"{x:.2f}".replace(".", ",")


def acc(rows):
    return sum(r["cls"] == "correct" for r in rows) / len(rows) if rows else None


def main(set_dir):
    name = os.path.basename(os.path.normpath(set_dir))
    rdir = os.path.join(ROOT, "results", name)
    models, tagged = {}, {}
    for p in sorted(glob.glob(os.path.join(rdir, "*__scored.jsonl"))):
        base = os.path.basename(p)[: -len("__scored.jsonl")]
        if base.startswith("mock__"):
            continue
        parts = base.split("__")
        if len(parts) > 2:  # дополнительное условие той же модели (метка tag), например с рассуждением
            tagged[(parts[1], parts[2])] = load(p)
        else:
            models[parts[1]] = load(p)
    if not models:
        sys.exit("нет оценённых ответов")
    order = sorted(models, key=lambda m: -(acc([r for r in models[m] if r["qtype"] == "depth" and r["fmt"] == "log"]) or 0))
    ns = sorted({r["n"] for rs in models.values() for r in rs})
    L = [f"# Анализ по глубине и номеру версии: {name}", "",
         "Вопросы о глубине (без ложных предпосылок и вопросов о забытых версиях), формат «лог». "
         "В клетке — доля верных ответов; в заголовке столбца — число вопросов на модель.", ""]

    def depth(rs, fmt="log"):
        return [r for r in rs if r["qtype"] == "depth" and r["fmt"] == fmt]

    for n in ns:
        ks = list(range(n))
        cnt = Counter(r["k"] for r in depth(models[order[-1]]) if r["n"] == n)
        L += [f"## Точность по глубине k, n = {n}", "",
              "| Модель | " + " | ".join(f"k = {k} ({cnt[k]})" for k in ks) + " |",
              "|---|" + "---|" * len(ks)]
        for m in order:
            d = [r for r in depth(models[m]) if r["n"] == n]
            L.append(f"| {m} | " + " | ".join(f2(acc([r for r in d if r["k"] == k])) for k in ks) + " |")
        L += ["", f"## Точность по номеру версии j = n − k, n = {n}", "",
              "| Модель | " + " | ".join(f"v{j}" for j in range(1, n + 1)) + " |", "|---|" + "---|" * n]
        for m in order:
            d = [r for r in depth(models[m]) if r["n"] == n]
            L.append(f"| {m} | " + " | ".join(f2(acc([r for r in d if r["gold_version"] == j]))
                                             for j in range(1, n + 1)) + " |")
        L.append("")

    L += ["## Влияние длины цепочки при фиксированной глубине", "",
          "| Модель | " + " | ".join(f"k = {k}: " + " / ".join(f"n = {n}" for n in ns) for k in (0, 1, 2)) + " |",
          "|---|---|---|---|"]
    for m in order:
        cells = []
        for k in (0, 1, 2):
            cells.append(" / ".join(f2(acc([r for r in depth(models[m]) if r["n"] == n and r["k"] == k])) for n in ns))
        L.append(f"| {m} | " + " | ".join(cells) + " |")
    L.append("")

    L += ["## Форматы памяти на одних и тех же вопросах", "",
          "Берутся только вопросы о глубине, на которые есть ответы модели в обоих форматах.", "",
          "| Модель | Лог | Список фактов | Вопросов |", "|---|---|---|---|"]
    for m in order:
        lg = {r["qid"]: r for r in depth(models[m], "log")}
        fc = {r["qid"]: r for r in depth(models[m], "facts")}
        common = sorted(set(lg) & set(fc))
        L.append(f"| {m} | {f2(acc([lg[q] for q in common]))} | {f2(acc([fc[q] for q in common]))} | {len(common)} |")
    L.append("")

    classes = ["correct", "later_version", "earlier_version", "refusal", "absent_value", "rejected_value",
               "other_slot", "unresolved"]
    L += ["## Классы ответов на вопросы о глубине (лог), доли", "",
          "| Модель | " + " | ".join(CLS_RU[c] for c in classes) + " |", "|---|" + "---|" * len(classes)]
    for m in order:
        d = depth(models[m])
        c = Counter(r["cls"] for r in d)
        L.append(f"| {m} | " + " | ".join(f2(c[x] / len(d)) for x in classes) + " |")
    L += ["", "Отказы по типу сценария (доля отказов среди вопросов о глубине):", "",
          "| Модель | " + " | ".join(["без доп. события", "несостоявшееся изменение", "мягкая просьба забыть",
                                       "строгая просьба забыть"]) + " |", "|---|---|---|---|---|"]
    for m in order:
        d = depth(models[m])
        cells = []
        for ex in ("none", "rejected", "forget_soft", "forget_ban"):
            dd = [r for r in d if r["extra"] == ex]
            cells.append(f2(sum(r["cls"] == "refusal" for r in dd) / len(dd)) if dd else "—")
        L.append(f"| {m} | " + " | ".join(cells) + " |")

    if tagged:
        sigmas = ["direct", "ordinal", "relative", "event_value", "event_desc"]
        L += ["", "## Дополнительные условия той же модели на одних и тех же входах", "",
              "Сравниваются только входы, на которые есть ответы в обоих условиях (вопросы о глубине). "
              "Точность — среднее по глубинам; затем по способам задания глубины.", "",
              "| Модель | Условие | Входов | Точность | " + " | ".join(sigmas) + " |",
              "|---|---|---|---|" + "---|" * len(sigmas)]
        for (m, tag), rs in tagged.items():
            if m not in models:
                continue
            t = {r["item_id"]: r for r in rs if r["qtype"] == "depth"}
            b = {r["item_id"]: r for r in models[m] if r["qtype"] == "depth"}
            common = sorted(set(t) & set(b))

            def macro(rows):
                by = {}
                for r in rows:
                    by.setdefault((r["n"], r["k"]), []).append(r["cls"] == "correct")
                return sum(sum(v) / len(v) for v in by.values()) / len(by) if by else None
            for lab, src in (("основное", b), (tag, t)):
                rows = [src[i] for i in common]
                L.append(f"| {m} | {lab} | {len(common)} | {f2(macro(rows))} | "
                         + " | ".join(f2(acc([r for r in rows if r["sigma"] == s])) for s in sigmas) + " |")

    # рисунки
    try:
        import matplotlib
        matplotlib.use("Agg")
        import matplotlib.pyplot as plt
        for n in [x for x in ns if x >= 5]:
            fig, axes = plt.subplots(1, 2, figsize=(11, 4))
            for m in order:
                d = [r for r in depth(models[m]) if r["n"] == n]
                axes[0].plot(range(n), [acc([r for r in d if r["k"] == k]) for k in range(n)], marker="o", label=m)
                axes[1].plot(range(1, n + 1), [acc([r for r in d if r["gold_version"] == j]) for j in range(1, n + 1)],
                             marker="o", label=m)
            axes[0].set_xlabel("глубина k")
            axes[1].set_xlabel("номер версии j")
            for ax in axes:
                ax.set_ylabel("доля верных ответов")
                ax.set_ylim(0, 1.02)
                ax.grid(alpha=0.3)
            axes[0].set_title(f"n = {n}: точность по глубине")
            axes[1].set_title(f"n = {n}: точность по номеру версии")
            axes[1].legend(fontsize=7, loc="lower right")
            fig.tight_layout()
            out = os.path.join(rdir, f"depth_n{n}.png")
            fig.savefig(out, dpi=150)
            plt.close(fig)
            L += ["", f"![n = {n}](depth_n{n}.png)"]
    except ImportError:
        pass

    text = "\n".join(L) + "\n"
    with open(os.path.join(rdir, "analysis.md"), "w", encoding="utf-8") as fh:
        fh.write(text)
    print(text)


if __name__ == "__main__":
    main(sys.argv[1])
