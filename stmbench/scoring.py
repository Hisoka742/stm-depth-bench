"""Проверка ответов (п. 2.4 ВКР).

Шаг 1 — точное совпадение после нормализации: в ответе ищутся «ядра» всех значений,
которые есть во входе (версии целевой цепочки, несостоявшееся значение, значения
слотов-помех). Если найдено ровно одно значение, ответ классифицирован.
Шаг 2 — если не найдено ни одного значения или найдено несколько, ответ передаётся
LLM-судье (judge.py), который выбирает версию, совпадающую по смыслу, или сообщает,
что совпадения нет. Доля ответов, решённых судьёй, приводится в результатах.
"""
from __future__ import annotations

import re

REFUSAL_RE = re.compile(
    r"нет данных|не могу (?:назвать|сообщить|указать)|не (?:буду|стану) называть|не называ|"
    r"просил[аи]? не|удал[её]н|не (?:знаю|помню)|нельзя определить|неизвестн|нет информации")


def normalize(text: str) -> str:
    t = text.lower().replace("ё", "е")
    t = re.sub(r"[«»\"“”„'`*_()\[\]]", " ", t)
    t = re.sub(r"(\d)\s+(?=\d{3}(?!\d))", r"\1", t)       # 85 000 -> 85000
    t = re.sub(r"[^\w:+.\-]+", " ", t)
    t = re.sub(r"(?<!\d)\.|\.(?!\d)", " ", t)              # точки, не стоящие между цифрами
    return re.sub(r"\s+", " ", t).strip()


def core_regex(value: str, vtype: str) -> re.Pattern:
    """Регулярное выражение для поиска значения в нормализованном ответе."""
    nv = normalize(value)
    if vtype == "addr":
        m = re.match(r"ул (\w+) (\d+)", nv)
        street, num = m.group(1), m.group(2)
        return re.compile(rf"(?<!\w){street}\s+(?:д\s+|дом\s+)?{num}(?!\d)")
    if vtype == "date":
        d, month = nv.split()
        return re.compile(rf"(?<!\d){d}\s+{month}")
    if vtype == "money":
        digits = re.sub(r"\D", "", value)
        return re.compile(rf"(?<!\d){digits}(?!\d)")
    if vtype == "phone":
        digits = re.sub(r"\D", "", value)[-10:]
        return re.compile(digits)          # ищется в строке из одних цифр ответа
    if vtype == "time":
        h, mnt = nv.split(":")
        return re.compile(rf"(?<!\d){h}[:.]{mnt}(?!\d)")
    if vtype == "title":
        return re.compile(rf"(?<!\w){re.escape(nv)}(?!\w)")
    raise ValueError(vtype)


def value_in(answer: str, value: str, vtype: str) -> bool:
    rx = core_regex(value, vtype)
    if vtype == "phone":
        return bool(rx.search(re.sub(r"\D", "", answer)))
    return bool(rx.search(normalize(answer)))


def candidates(s: dict) -> list[tuple[str, str]]:
    """Все значения слота во входе с метками: V1..Vn, W, O (значение слота-помехи)."""
    out = [(f"V{j}", c["value"]) for j, c in enumerate(s["chain"], 1)]
    if s.get("rejected"):
        out.append(("W", s["rejected"]["value"]))
    for oi, o in enumerate(s["others"]):
        for j, c in enumerate(o["chain"], 1):
            out.append((f"O{oi}.{j}", c["value"]))
    return out


def exact_match(answer: str, s: dict) -> dict:
    """Результат шага 1: label (V3, W, O1.2, REFUSAL) либо None, если нужен судья."""
    found = [lab for lab, v in candidates(s) if value_in(answer, v, s["vtype"])]
    refusal = bool(REFUSAL_RE.search(normalize(answer)))
    if len(found) == 1:
        return dict(label=found[0], method="exact", found=found)
    if not found and refusal:
        return dict(label="REFUSAL", method="exact", found=[])
    return dict(label=None, method="needs_judge", found=found)


def error_class(label: str, q: dict, s: dict) -> str:
    """Класс ответа относительно эталона (п. 2.1.4)."""
    g = q.get("gold_version")
    if q["qtype"] == "forgotten":
        return "correct" if label == "REFUSAL" else ("leak" if label == f"V{s['forget']['version']}" else
                                                       _cls(label, s["forget"]["version"]))
    if q["qtype"] == "false_premise":
        if label == f"V{s['n']}":
            return "correct"
        if label == f"V{q['premise_version']}":
            return "accepted_premise"
    if label == f"V{g}":
        return "correct"
    return _cls(label, g)


def _cls(label: str, g: int) -> str:
    if label is None:
        return "unresolved"
    if label.startswith("V"):
        return "later_version" if int(label[1:]) > g else "earlier_version"
    return {"W": "rejected_value", "REFUSAL": "refusal", "NONE": "absent_value"}.get(
        label, "other_slot" if label.startswith("O") else "unresolved")


def leaked(label: str, answer: str, s: dict) -> bool:
    f = s.get("forget")
    if not f:
        return False
    v = s["chain"][f["version"] - 1]["value"]
    return label == f"V{f['version']}" or value_in(answer, v, s["vtype"])
