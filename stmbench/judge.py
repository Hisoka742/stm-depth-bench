"""LLM-судья — запасной способ проверки (п. 2.4 ВКР).

Судья вызывается только для ответов, которые не удалось классифицировать точной
проверкой (не найдено ни одного значения или найдено несколько). Судья не знает,
какое значение эталонное: ему даются вопрос, ответ и все значения слота из входа
под нейтральными перемешанными метками. Он сообщает, с каким значением ответ совпадает
по смыслу, либо что ответ — отказ, либо что совпадения нет.
"""
from __future__ import annotations

import json
import random
import re

from .scoring import candidates

JUDGE_SYSTEM = (
    "Ты проверяешь ответы в тесте на память диалоговой модели. Тебе даны вопрос пользователя, "
    "ответ модели и список значений, которые встречались в диалоге, каждое со своей меткой. "
    "Определи, какое значение из списка модель дала в качестве ответа на вопрос. Значение может быть "
    "записано иначе: с другими сокращениями, в другом падеже, в другом формате даты, времени, суммы "
    "или номера телефона, внутри развёрнутого предложения. Если ответ называет несколько значений и "
    "нельзя понять, какое из них модель считает ответом, верни MULTIPLE. Если модель отказывается "
    "отвечать или сообщает, что данных нет, верни REFUSAL. Если названное значение не совпадает ни с "
    "одним значением из списка, верни NONE. Верни только JSON вида {\"label\": \"<метка>\"}."
)

LETTERS = [chr(c) for c in range(ord("A"), ord("Z") + 1)]


def judge_prompt(s: dict, q: dict, answer: str, seed: int = 0) -> tuple[list[dict], dict]:
    cands = candidates(s)
    rng = random.Random(f"{q['qid']}|{seed}")
    order = list(range(len(cands)))
    rng.shuffle(order)
    mapping = {}
    lines = []
    for li, ci in enumerate(order):
        lab = LETTERS[li] if li < 26 else f"Z{li}"
        mapping[lab] = cands[ci][0]
        lines.append(f"{lab}: {cands[ci][1]}")
    user = (f"Слот: {s['slot']}\nВопрос пользователя: {q['text']}\nОтвет модели: {answer}\n\n"
            "Значения из диалога:\n" + "\n".join(lines))
    return [{"role": "system", "content": JUDGE_SYSTEM}, {"role": "user", "content": user}], mapping


def parse_judge(text: str, mapping: dict) -> str:
    m = re.search(r"\{.*?\}", text, re.S)
    lab = None
    if m:
        try:
            lab = json.loads(m.group(0)).get("label")
        except json.JSONDecodeError:
            lab = None
    if lab is None:
        m2 = re.search(r"\b(MULTIPLE|REFUSAL|NONE|[A-Z])\b", text)
        lab = m2.group(1) if m2 else "UNPARSED"
    lab = str(lab).strip().upper()
    if lab in ("MULTIPLE", "REFUSAL", "NONE", "UNPARSED"):
        return lab
    return mapping.get(lab, "UNPARSED")
