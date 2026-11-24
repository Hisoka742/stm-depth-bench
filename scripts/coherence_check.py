"""Проверка связности готовых диалогов с помощью LLM (п. 2.3 ВКР).

    python scripts/coherence_check.py data/pilot_bank [--model openai/gpt-6.1-terra --reasoning low]

Каждый диалог (в том положении цепочки, в котором он подаётся моделям) отправляется
модели-проверяющему с нумерацией реплик. Модель ищет места, противоречащие здравому смыслу
или предыдущим репликам, и указывает номер реплики. Результат: results/<набор>/coherence.jsonl
и coherence.md со списком найденных мест. Автоматические правила (validate.py) проверяют
разметку, а эта проверка — смысл; найденные места разбираются вручную, после чего исправляются
шаблоны генератора.
"""
from __future__ import annotations

import argparse
import json
import os
import re
import sys
from concurrent.futures import ThreadPoolExecutor

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)
from stmbench.openrouter import chat  # noqa: E402
from stmbench.render import dialog_turns  # noqa: E402

SYSTEM = (
    "Ты редактор синтетических диалогов. Ниже диалог клиента с ассистентом банка, реплики "
    "пронумерованы. Клиент несколько раз меняет сведения (адреса, даты, суммы, номера, время, карты) "
    "и иногда исправляет оговорки; частые изменения сами по себе нормальны. Клиент также может "
    "задавать посторонние вопросы о банке и между делом упоминать другие адреса, даты, суммы. "
    "Найди места, которые противоречат здравому смыслу или предыдущим репликам, например: новое "
    "значение не соответствует названной причине (просят сдвинуть позже, а дата становится раньше; "
    "расходы выросли, а сумма уменьшилась); неправдоподобное значение; клиент исправляет «ошибку» в "
    "значении, которое только что подтвердил; ответ ассистента не подходит к реплике; упоминание "
    "между делом противоречит остальному диалогу. Для каждого места укажи номер реплики и кратко "
    "опиши проблему. Верни только JSON вида {\"problems\": [{\"turn\": 12, \"problem\": \"...\"}]}; "
    "если проблем нет, верни {\"problems\": []}."
)


def dialog_text(s: dict, position: str) -> tuple[str, list]:
    turns, _ = dialog_turns(s, position)
    lines = [f"{i}. {'Клиент' if r == 'u' else 'Ассистент'}: {t}" for i, (r, t) in enumerate(turns)]
    return "\n".join(lines), turns


def check(s, model, max_tokens, extra):
    pos = (s.get("positions") or ["middle"])[0]
    text, turns = dialog_text(s, pos)
    r = chat(model, [{"role": "system", "content": SYSTEM}, {"role": "user", "content": text}],
             temperature=0.0, max_tokens=max_tokens, extra=extra)
    m = re.search(r"\{.*\}", r["content"], re.S)
    try:
        probs = json.loads(m.group(0))["problems"] if m else None
    except (json.JSONDecodeError, KeyError):
        probs = None
    out = dict(sid=s["id"], position=pos, problems=probs, raw=None if probs is not None else r["content"],
               cost=(r.get("usage") or {}).get("cost"))
    for p in probs or []:
        t = p.get("turn")
        if isinstance(t, int) and 0 <= t < len(turns):
            p["text"] = turns[t][1]
    return out


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("set_dir")
    ap.add_argument("--model", default="openai/gpt-6.1-terra")
    ap.add_argument("--max-tokens", type=int, default=8000)
    ap.add_argument("--reasoning", default="low", help="effort рассуждения проверяющей модели или none")
    ap.add_argument("--only", nargs="*")
    args = ap.parse_args()
    name = os.path.basename(os.path.normpath(args.set_dir))
    out_dir = os.path.join(ROOT, "results", name)
    os.makedirs(out_dir, exist_ok=True)
    scen = [json.loads(x) for x in open(os.path.join(args.set_dir, "scenarios.jsonl"), encoding="utf-8")]
    if args.only:
        scen = [s for s in scen if s["id"] in args.only]
    extra = {"reasoning": {"effort": args.reasoning}}
    with ThreadPoolExecutor(6) as ex:
        res = list(ex.map(lambda s: check(s, args.model, args.max_tokens, extra), scen))
    with open(os.path.join(out_dir, "coherence.jsonl"), "w", encoding="utf-8") as f:
        for r in res:
            f.write(json.dumps(r, ensure_ascii=False) + "\n")
    flagged = [r for r in res if r["problems"]]
    failed = [r for r in res if r["problems"] is None]
    L = [f"# Проверка связности диалогов: {name}", "",
         f"Проверяющая модель: {args.model} (рассуждение: {args.reasoning}). Диалогов: {len(res)}, "
         f"с найденными местами: {len(flagged)}, без ответа: {len(failed)}.", ""]
    for r in flagged:
        L.append(f"## {r['sid']}")
        for p in r["problems"]:
            L.append(f"- реплика {p.get('turn')}: {p.get('problem')}" + (f"  \n  > {p['text']}" if p.get("text") else ""))
        L.append("")
    with open(os.path.join(out_dir, "coherence.md"), "w", encoding="utf-8") as f:
        f.write("\n".join(L) + "\n")
    print("\n".join(L))
    print(f"стоимость: {sum(r['cost'] or 0 for r in res):.4f} $")


if __name__ == "__main__":
    main()
