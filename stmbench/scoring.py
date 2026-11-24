"""Проверка ответов (п. 2.4 ВКР).

Сравнение с эталоном всегда выполняет код.
Шаг 1 — извлечение: из ответа регулярными выражениями извлекаются все значения типа слота
(адреса, даты, суммы, телефоны, время, карты) и приводятся к канонической форме
(stmbench/values.py: «07:30» = «7:30» = «7.30», «260 тыс.» = «260 000 рублей»). Каноническая
форма сравнивается с каноническими формами всех значений из входа (версии целевой цепочки,
несостоявшееся значение, значения слотов-помех). Значение, которого во входе нет, получает
метку NONE. Если в ответе одно значение (или одно и то же несколько раз), ответ классифицирован.
Шаг 2 — если значений нет или их несколько, LLM-судья только выписывает из ответа значение,
которое модель дала как ответ, в каноническом формате (judge.py); сопоставление с эталоном
снова выполняет код. Списка значений из диалога судья не видит.
"""
from __future__ import annotations

import re

from .values import TYPES

REFUSAL_RE = re.compile(
    r"нет данных|не могу (?:назвать|сообщить|указать)|не (?:буду|стану) называть|не называ|"
    r"просил[аи]? не|удал[её]н|не (?:знаю|помню)|нельзя определить|неизвестн|нет информации")


def normalize(text: str) -> str:
    t = text.lower().replace("ё", "е")
    t = re.sub(r"[«»\"“”„'`*_()\[\]]", " ", t)
    t = re.sub(r"[^\w:+.\-]+", " ", t)
    return re.sub(r"\s+", " ", t).strip()


def value_in(answer: str, value: str, vtype: str) -> bool:
    vt = TYPES[vtype]
    return vt.canon(value) in vt.extract(answer)


def candidates(s: dict) -> list[tuple[str, str]]:
    """Все значения слота во входе с метками: V1..Vn, W, O (значение слота-помехи)."""
    out = [(f"V{j}", c["value"]) for j, c in enumerate(s["chain"], 1)]
    if s.get("rejected"):
        out.append(("W", s["rejected"]["value"]))
    for oi, o in enumerate(s["others"]):
        for j, c in enumerate(o["chain"], 1):
            out.append((f"O{oi}.{j}", c["value"]))
    return out


def label_of(canon_values: list, s: dict) -> list[str]:
    """Метки для канонических значений: метка значения из входа или NONE."""
    vt = TYPES[s["vtype"]]
    cmap = {vt.canon(v): lab for lab, v in candidates(s)}
    out = []
    for c in canon_values:
        lab = cmap.get(c, "NONE")
        if lab not in out:
            out.append(lab)
    return out


def exact_match(answer: str, s: dict) -> dict:
    """Результат шага 1: label (V3, W, O1.2, NONE, REFUSAL) либо None, если нужен судья."""
    vt = TYPES[s["vtype"]]
    found = label_of(vt.extract(answer), s)
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
