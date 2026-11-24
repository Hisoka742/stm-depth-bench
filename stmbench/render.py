"""Отрисовка сценария во вход модели: положение цепочки p и формат памяти f (п. 2.1.5, 2.2)."""
from __future__ import annotations

from .lang import resolve_gender

SYSTEM_LOG = (
    "Ты — ассистент банка, который ведёт этот диалог с клиентом. Ответь на последнее сообщение "
    "клиента, опираясь только на сведения из диалога. Назови только значение, о котором "
    "спрашивают, без пояснений. Если клиент просит что-то сделать, назови значение, с которым ты "
    "это сделаешь. Если клиент просил не называть это значение, ответь: «нет данных»."
)
SYSTEM_FACTS = (
    "Ты — ассистент банка, который ведёт диалог с клиентом. Ниже приведены сведения, извлечённые "
    "из этого диалога в порядке их появления: для каждого сведения указаны слот, значение, номер "
    "версии и описание изменения, а также другие события диалога. Ответь на последнее сообщение "
    "клиента, опираясь только на эти сведения. Назови только значение, о котором спрашивают, без "
    "пояснений. Если клиент просит что-то сделать, назови значение, с которым ты это сделаешь. "
    "Если клиент просил не называть это значение, ответь: «нет данных»."
)

POSITIONS = ("start", "middle", "end")


def dialog_turns(s: dict, position: str) -> tuple[list[tuple[str, str]], dict]:
    """Ходы диалога и разметка: номер хода каждой записи версии.

    Посторонний блок pos_filler целиком стоит после цепочки (start), делится пополам (middle)
    или целиком стоит перед ней (end). Остальное содержание одинаково при любом p.
    """
    pf = s["pos_filler"]
    cut = {"start": 0, "middle": len(pf) // 2, "end": len(pf)}[position]
    blocks = [dict(kind="intro", turns=s["intro"])] + pf[:cut] + s["region"] + pf[cut:]
    turns: list[tuple[str, str]] = []
    meta = {"record_turn": {}, "chain_start": None, "chain_end": None}
    for b in blocks:
        if b.get("kind") == "record" and b["slot"] == "target":
            idx = len(turns) + b.get("value_turn", 0)  # ход пользователя со значением (с нуля)
            meta["record_turn"][b["version"]] = idx
            if b["version"] == 1:
                meta["chain_start"] = idx
            meta["chain_end"] = len(turns) + len(b["turns"])
        turns.extend(b["turns"])
    meta["n_turns"] = len(turns)
    return turns, meta


def messages_log(s: dict, q: dict, position: str) -> list[dict]:
    turns, _ = dialog_turns(s, position)
    msgs = [{"role": "system", "content": SYSTEM_LOG}]
    for role, text in turns:
        msgs.append({"role": "user" if role == "u" else "assistant", "content": text})
    msgs.append({"role": "user", "content": q["text"]})
    return msgs


CHANGE_DESC = {
    "first": "первое значение",
    "explicit": "явная замена",
    "implicit": "новое значение без слов о замене",
    "correction": "исправление ошибочно названного значения",
}


def facts_eligible(s: dict) -> bool:
    """Список фактов строится для всех сценариев: форматы сравниваются на одних и тех же."""
    return True


def fact_lines(s: dict) -> list[str]:
    """Сведения из диалога в порядке появления: записи версий и прочие события целевого слота."""
    lines = []
    for b in s["region"]:
        kind = b.get("kind")
        if kind == "record":
            slot = s["slot"] if b["slot"] == "target" else s["others"][int(b["slot"][5:])]["slot"]
            desc = CHANGE_DESC[b["change"]]
            if b["reason"]:
                desc += f" (причина: {resolve_gender(b['reason'], s['user_gender'])})"
            lines.append(f"слот: {slot}; значение: {b['value']}; версия: {b['version']}; изменение: {desc}")
        elif kind == "rejected":
            lines.append(f"слот: {s['slot']}; предложено значение {b['value']}, но клиент отказался "
                         f"и оставил действующее")
        elif kind == "forget":
            v = s["chain"][b["version"] - 1]["value"]
            if s["forget"]["mode"] == "ban":
                lines.append(f"слот: {s['slot']}; клиент попросил удалить значение {v} из записей и "
                             f"не называть его, даже если он сам о нём спросит")
            else:
                lines.append(f"слот: {s['slot']}; клиент сказал, что значение {v} можно забыть")
    return [f"{i}. {t}" for i, t in enumerate(lines, 1)]


def messages_facts(s: dict, q: dict) -> list[dict]:
    body = "Сведения из диалога:\n" + "\n".join(fact_lines(s))
    return [{"role": "system", "content": SYSTEM_FACTS},
            {"role": "user", "content": body + "\n\nВопрос пользователя: " + q["text"]}]


def render_items(s: dict, positions=POSITIONS, with_facts: bool = True) -> list[dict]:
    """Все входы модели для сценария: (вопрос × позиция) в формате лога и вопрос в формате фактов."""
    items = []
    for p in positions:
        _, meta = dialog_turns(s, p)
        for q in s["questions"]:
            items.append(dict(item_id=f"{q['qid']}-log-{p}", sid=s["id"], qid=q["qid"], fmt="log",
                              position=p, messages=messages_log(s, q, p),
                              dist_turns=meta["n_turns"] - meta["record_turn"].get(q["gold_version"] or 0, 0)
                              if q.get("gold_version") else None))
    if with_facts and facts_eligible(s):
        for q in s["questions"]:
            items.append(dict(item_id=f"{q['qid']}-facts", sid=s["id"], qid=q["qid"], fmt="facts",
                              position=None, messages=messages_facts(s, q), dist_turns=None))
    return items
