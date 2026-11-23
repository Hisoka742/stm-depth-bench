"""Автоматическая проверка разметки сценария (п. 2.3 ВКР).

Каждое правило соответствует одному из требований однозначности эталона.
Возвращается список нарушений; пустой список — сценарий корректен.
"""
from __future__ import annotations

import re

from .domains import DOMAINS
from .generator import CHANGE_MARKERS
from .lang import CHANGES_AGO, ordinal_instr, resolve_gender
from .render import POSITIONS, dialog_turns
from .scoring import value_in


def validate(s: dict) -> list[str]:
    errs: list[str] = []
    dom = DOMAINS[s["domain"]]
    rx = re.compile(dom.value_regex)
    n = s["n"]
    vals = [c["value"] for c in s["chain"]]

    # 1. значения попарно различны во всём диалоге
    allv = vals + [c["value"] for o in s["others"] for c in o["chain"]]
    if s.get("rejected"):
        allv.append(s["rejected"]["value"])
    if len(set(allv)) != len(allv):
        errs.append("повторяются значения слотов")
    for v in allv:
        if not rx.fullmatch(v):
            errs.append(f"значение не распознаётся шаблоном типа: {v}")
    # «ядра» значений не должны совпадать (иначе точная проверка неоднозначна)
    for i, a in enumerate(allv):
        for b in allv[i + 1:]:
            if value_in(a, b, s["vtype"]) or value_in(b, a, s["vtype"]):
                errs.append(f"значения неразличимы при точной проверке: {a} / {b}")

    for p in POSITIONS:
        turns, meta = dialog_turns(s, p)
        # 2. чередование ролей
        roles = [r for r, _ in turns]
        if roles[0] != "u" or roles[-1] != "a" or any(roles[i] == roles[i + 1] for i in range(len(roles) - 1)):
            errs.append(f"[{p}] нарушено чередование ролей")
        # 3. записи версий идут по порядку и содержат значение
        rt = meta["record_turn"]
        if sorted(rt) != list(range(1, n + 1)) or any(rt[i] >= rt[i + 1] for i in range(1, n)):
            errs.append(f"[{p}] нарушен порядок записей")
        for j in range(1, n + 1):
            if vals[j - 1] not in turns[rt[j]][1]:
                errs.append(f"[{p}] в ходе записи v{j} нет значения")

    turns, meta = dialog_turns(s, "end")
    rt = meta["record_turn"]
    # 4. в ходах неявного обновления нет слов о замене (во всех ходах записи)
    rec_blocks = {b["version"]: b for b in s["region"] if b.get("kind") == "record" and b["slot"] == "target"}
    for j in range(2, n + 1):
        if s["chain"][j - 1]["change"] == "implicit":
            for _, t in rec_blocks[j]["turns"]:
                m = CHANGE_MARKERS.search(t)
                if m:
                    errs.append(f"в неявном обновлении v{j} есть показатель замены «{m.group(0)}»: {t}")
    # 5. посторонние ходы и вводная часть не содержат значений слота
    for b in [dict(turns=s["intro"])] + s["pos_filler"] + [x for x in s["region"] if x.get("kind") == "filler"]:
        for _, t in b["turns"]:
            if rx.search(t):
                errs.append(f"в постороннем ходе есть значение слота: {t}")
    # 6. описание события для вопросов через описание встречается ровно в одном ходе
    user_texts = [t for r, t in turns if r == "u"]
    for j in range(2, n + 1):
        reason = s["chain"][j - 1]["reason"]
        r = resolve_gender(reason, s["user_gender"])
        hits = [t for t in user_texts if r.lower() in t.lower()]
        block_u = [t for role, t in rec_blocks[j]["turns"] if role == "u"]
        if len(hits) != 1:
            errs.append(f"описание события v{j} встречается {len(hits)} раз: {r}")
        elif hits[0] not in block_u:
            errs.append(f"описание события v{j} стоит не в записи v{j}")
    # 7. просьба забыть стоит после смены версии, и после неё забытое значение не звучит
    if s.get("forget"):
        fj = s["forget"]["version"]
        fi = next(i for i, (r, t) in enumerate(turns) if r == "u" and ("забыть" in t or "удалите" in t)
                  and vals[fj - 1] in t)
        if fj < n and fi < rt[fj + 1]:
            errs.append("просьба забыть стоит до смены забываемой версии")
        if any(vals[fj - 1] in t for _, t in turns[fi + 2:]):
            errs.append("забытое значение упоминается после просьбы забыть")
    # 8. эталоны вопросов
    forg = s.get("forget")
    g = dom.gender
    for q in s["questions"]:
        if q["qtype"] == "false_premise":
            if q["gold"] != vals[-1] or vals[q["premise_version"] - 1] not in q["text"]:
                errs.append(f"{q['qid']}: неверная ложная предпосылка")
            continue
        j = n - q["k"]
        if q["gold_version"] != j:
            errs.append(f"{q['qid']}: эталон не равен v(n-k)")
        if forg and j == forg["version"]:
            if forg["mode"] == "soft":
                errs.append(f"{q['qid']}: вопрос о версии, которую мягко просили забыть")
            elif q["gold"] is not None:
                errs.append(f"{q['qid']}: эталон для запрещённой версии должен быть ⊥")
        elif q["gold"] != vals[j - 1]:
            errs.append(f"{q['qid']}: эталон не совпадает со значением версии")
        if q["sigma"] == "ordinal":
            if q["direction"] == "start" and ordinal_instr(j, g) not in q["text"]:
                errs.append(f"{q['qid']}: неверное порядковое числительное")
            if q["direction"] == "end" and CHANGES_AGO[q["k"]] not in q["text"]:
                errs.append(f"{q['qid']}: неверное число изменений")
            if "ошибоч" not in q["text"] and "Исправления" not in q["text"]:
                errs.append(f"{q['qid']}: в порядковом вопросе нет правила счёта исправлений")
        if q["sigma"] == "event_value" and vals[j] not in q["text"]:
            errs.append(f"{q['qid']}: в вопросе нет следующего значения")
    return errs
