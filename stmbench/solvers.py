"""Нижние границы точности (п. 2.1.4 ВКР).

1. Стратегии с фиксированной позицией: всегда называют версию v_n, v_1 или v_{n-1};
   стратегия «сейчас/раньше» называет v_n на вопрос о текущем значении и v_1 на любой
   вопрос о прошлом. Они используют разметку цепочки и показывают, чего можно добиться,
   совсем не учитывая глубину.
2. Поверхностные эвристики: не используют разметку, а работают с текстом диалога и
   формулировкой вопроса. Из диалога выписываются все упоминания значений нужного типа
   (по регулярному выражению), при желании только в репликах пользователя и только в
   ходах, где названа сущность или слот. Из упоминаний строится список различных значений
   в порядке первого или последнего упоминания, и по формулировке вопроса из него
   берётся элемент: последний, первый, предпоследний, j-й с начала, k-й с конца,
   предшествующий названному значению, предшествующий ходу с описанием события.
   Для каждого способа задания глубины приводится лучший из вариантов эвристики.
"""
from __future__ import annotations

import itertools
import re
from collections import defaultdict

from .domains import DOMAINS

# ---------------------------------------------------------------- фиксированные позиции
FIXED = {
    "S_last": lambda q, n: n,
    "S_first": lambda q, n: 1,
    "S_prev": lambda q, n: n - 1,
    "S_now_or_first": lambda q, n: n if q["k"] == 0 else 1,
}


def fixed_strategy_answer(name: str, q: dict, n: int) -> int:
    return FIXED[name](q, n)


# ---------------------------------------------------------------- поверхностные эвристики
VARIANTS = list(itertools.product(["user", "all"], ["none", "entity", "slot"], ["first", "last"]))


def _stems(text: str) -> set[str]:
    return {w[:5] for w in re.findall(r"[а-яё]+", text.lower()) if len(w) > 3}


def _entity_forms(s: dict) -> list[str]:
    dom = DOMAINS[s["domain"]]
    ent = next(e for e in dom.entities if e["E"] == s["entity"])
    return [v.lower() for k, v in ent.items() if k in ("E", "E_gen", "E_dat", "E_acc", "q")]


def _mentions(s: dict, turns, role: str, slotf: str):
    """Список (номер хода, значение) в порядке появления."""
    dom = DOMAINS[s["domain"]]
    rx = re.compile(dom.value_regex)
    forms = _entity_forms(s)
    slot_l = s["slot"].lower()
    out = []
    for i, (r, text) in enumerate(turns):
        if role == "user" and r != "u":
            continue
        tl = text.lower()
        if slotf == "entity" and not any(f in tl for f in forms):
            continue
        if slotf == "slot" and slot_l not in tl:
            continue
        for m in rx.finditer(text):
            out.append((i, m.group(0)))
    return out


def _distinct(mentions, order: str) -> list[str]:
    if order == "first":
        seen, out = set(), []
        for _, v in mentions:
            if v not in seen:
                seen.add(v)
                out.append(v)
        return out
    last = {}
    for idx, (_, v) in enumerate(mentions):
        last[v] = idx
    return [v for v, _ in sorted(last.items(), key=lambda kv: kv[1])]


def _pick(lst, i):
    try:
        return lst[i] if (i >= 0 and i < len(lst)) or (i < 0 and -i <= len(lst)) else None
    except IndexError:
        return None


def heuristic_answer(s: dict, q: dict, turns, variant) -> str | None:
    role, slotf, order = variant
    mentions = _mentions(s, turns, role, slotf)
    lst = _distinct(mentions, order)
    sig = q["sigma"]
    n = s["n"]
    if not lst:
        return None
    if sig in ("direct", "false_premise"):
        return lst[-1]
    k = q["k"]
    if sig == "ordinal":
        j = n - k
        if q["direction"] == "start":
            return _pick(lst, j - 1)
        return _pick(lst, -1 - k)
    if sig == "relative":
        return lst[0] if k == n - 1 else _pick(lst, -2)
    if sig == "event_value":
        x = re.search(r"до варианта (.+)\?$", q["text"]).group(1)
        x = x if x.startswith("«") and DOMAINS[s["domain"]].vtype == "title" else x.strip("«»")
        positions = [p for p, (_, v) in enumerate(mentions) if v == x]
        if not positions:
            return None
        pos = positions[0] if order == "first" else positions[-1]
        before = [v for _, v in mentions[:pos] if v != x]
        return before[-1] if before else None
    if sig == "event_desc":
        clause = q["text"].split(", что ", 1)[1].rstrip("?")
        target = _stems(clause)
        best, best_i = 0, None
        for i, (r, text) in enumerate(turns):
            if r != "u":
                continue
            sc = len(target & _stems(text))
            if sc > best:
                best, best_i = sc, i
        if best_i is None:
            return None
        before = [v for i, v in mentions if i < best_i]
        return before[-1] if before else None
    return None


def macro(records) -> float | None:
    """Среднее по (n, k) долей верных ответов."""
    if not records:
        return None
    by = defaultdict(list)
    for n, k, ok in records:
        by[(n, k)].append(ok)
    return sum(sum(v) / len(v) for v in by.values()) / len(by)
