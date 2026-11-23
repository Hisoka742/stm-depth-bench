"""Выгрузка логов прогона в читаемую таблицу Excel.

    python scripts/export_logs.py data/pilot [--out results/pilot/logs.xlsx]

Лист «Сводка» — таблица comparison.md; по листу на модель: каждый запрос с вопросом,
эталоном, ответом модели, итогом проверки (точно / судья), классом ответа, причиной
завершения, числом токенов и стоимостью; лист «Судья» — все обращения к судье.
"""
from __future__ import annotations

import argparse
import glob
import json
import os

from openpyxl import Workbook
from openpyxl.styles import Alignment, Font, PatternFill
from openpyxl.utils import get_column_letter

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
FILL = {"correct": "E2F0D9", "unresolved": "FFF2CC"}
ERR_FILL = "FCE4D6"


def load_jsonl(path):
    if not os.path.exists(path):
        return []
    with open(path, encoding="utf-8") as f:
        return [json.loads(x) for x in f if x.strip()]


def sheet(ws, header, rows, widths):
    ws.append(header)
    for c in ws[1]:
        c.font = Font(bold=True)
    for r in rows:
        ws.append(r)
    for i, w in enumerate(widths, 1):
        ws.column_dimensions[get_column_letter(i)].width = w
    ws.freeze_panes = "A2"
    ws.auto_filter.ref = ws.dimensions


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("set_dir")
    ap.add_argument("--out")
    args = ap.parse_args()
    name = os.path.basename(os.path.normpath(args.set_dir))
    rdir = os.path.join(ROOT, "results", name)
    out = args.out or os.path.join(rdir, "logs.xlsx")
    scen = {s["id"]: s for s in load_jsonl(os.path.join(args.set_dir, "scenarios.jsonl"))}
    qmap = {q["qid"]: q for s in scen.values() for q in s["questions"]}

    wb = Workbook()
    ws = wb.active
    ws.title = "Сводка"
    comp = os.path.join(rdir, "comparison.md")
    if os.path.exists(comp):
        with open(comp, encoding="utf-8") as f:
            for line in f:
                line = line.rstrip("\n")
                if line.startswith("|---"):
                    continue
                if line.startswith("|"):
                    ws.append([c.strip().strip("*") for c in line.strip("|").split("|")])
                else:
                    ws.append([line])
        ws.column_dimensions["A"].width = 34

    header = ["item_id", "сценарий", "n", "m", "дополнительное событие", "формат", "положение", "тип вопроса",
              "глубина k", "способ", "вопрос", "эталон", "эталонная версия", "ответ модели", "распознано как",
              "проверка", "класс ответа", "утечка", "finish_reason", "вх. токены", "вых. токены", "стоимость, $",
              "провайдер", "время запроса"]
    widths = [22, 9, 4, 4, 14, 8, 10, 12, 8, 12, 60, 24, 9, 60, 10, 9, 16, 8, 10, 9, 9, 11, 14, 19]
    for p in sorted(glob.glob(os.path.join(rdir, "*.jsonl"))):
        base = os.path.basename(p)[:-len(".jsonl")]
        if base.endswith("__scored") or base.startswith(("judge", "mock__")):
            continue
        raw = {r["item_id"]: r for r in load_jsonl(p) if r.get("error") is None}
        scored = {r["item_id"]: r for r in load_jsonl(os.path.join(rdir, base + "__scored.jsonl"))}
        rows = []
        for iid in sorted(raw):
            r, sc = raw[iid], scored.get(iid, {})
            q, s = qmap[r["qid"]], scen[r["qid"].split("-")[0]]
            u = r.get("usage") or {}
            rows.append([iid, s["id"], s["n"], s["m"], s["extra"], r["fmt"], r.get("position") or "—", q["qtype"],
                         q.get("k"), q["sigma"], q["text"], q["gold"] if q["gold"] is not None else "⊥ (отказ)",
                         q.get("gold_version"), r["response"], sc.get("label"), sc.get("method"), sc.get("cls"),
                         sc.get("leak"), r.get("finish_reason"), u.get("prompt_tokens"), u.get("completion_tokens"),
                         u.get("cost"), r.get("provider"), r.get("time")])
        w = wb.create_sheet(base.split("__", 1)[1][:31])
        sheet(w, header, rows, widths)
        for row in w.iter_rows(min_row=2):
            cls = row[16].value
            color = FILL.get(cls, ERR_FILL)
            for c in (row[13], row[16]):
                c.fill = PatternFill("solid", fgColor=color)
            for c in (row[10], row[13]):
                c.alignment = Alignment(wrap_text=True, vertical="top")

    for jp in glob.glob(os.path.join(rdir, "judge__*.jsonl")):
        rows = [[j["qid"], qmap[j["qid"]]["text"] if j["qid"] in qmap else "", j["answer"], j["raw"], j["label"]]
                for j in load_jsonl(jp)]
        w = wb.create_sheet("Судья")
        sheet(w, ["вопрос (id)", "вопрос", "ответ модели", "ответ судьи", "распознанная версия"], rows,
              [12, 60, 60, 16, 12])
    jc = load_jsonl(os.path.join(rdir, "judge_check.jsonl"))
    if jc:
        rows = [[j["qid"], j["answer"], j["expect"], j["exact"], j["judge"], j["judge"] == j["expect"]] for j in jc]
        w = wb.create_sheet("Проверка судьи")
        sheet(w, ["вопрос (id)", "тестовый ответ", "ожидаемая версия", "точная проверка", "судья", "судья верно"],
              rows, [12, 60, 12, 12, 12, 10])
    wb.save(out)
    print("saved", out)


if __name__ == "__main__":
    main()
