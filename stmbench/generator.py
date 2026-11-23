"""Генератор сценариев и вопросов (п. 2.2 ВКР).

Сценарий строится в три шага:
  1) выбираются значения целевой цепочки v1..vn, цепочки m однотипных слотов-помех,
     виды изменений, описания событий и дополнительные события;
  2) из событий собирается «область цепочки»: записи версий, записи слотов-помех,
     посторонние ходы, случайные упоминания значений, предложение несостоявшегося
     изменения, просьба забыть;
  3) к цепочке строится набор вопросов с эталонами по формуле a*(q) = v_{n-k}.
Положение цепочки в контексте (начало/середина/конец) задаётся при отрисовке
(render.py), содержание сценария при этом не меняется.
"""
from __future__ import annotations

import random
import re

from .domains import DOMAINS, Domain
from .lang import SLOT_FORMS, CHANGES_AGO, cap, join_ru, ordinal_instr, resolve_gender

CHANGE_TYPES = ("explicit", "implicit", "correction")

# Лексические показатели замены. В ходах неявного обновления их быть не должно.
CHANGE_MARKERS = re.compile(
    r"теперь|вместо|измен|помен|замен|смен|перемен|перенес|перенос|переназнач|ошиб|исправ|"
    r"поправ|раньше|прежн|больше не|уже не|передума|отмен|\bнов\w*|\bдруг(ой|ую|ое|ого|им|ая)\b",
    re.IGNORECASE)

ACK_FIRST = ["Записано: {slot} — {v}.", "Принято: {v}.", "Хорошо, записано."]
ACK_EXPLICIT = ["Хорошо, {slot} {izmenen}: было {old}, стало {new}.", "Готово: {slot} — {new}.",
                "Понятно, теперь {new}."]
ACK_IMPLICIT = ["Записано: {slot} — {new}.", "Хорошо, {new}.", "Принято."]
ACK_CORRECTION = ["Исправлено: {slot} — {new}.", "Исправлено: вместо {old} — {new}.", "Хорошо, исправлено."]
ACK_STRAY = ["Буду знать.", "Ясно, спасибо.", "Понятно."]


def quote(v: str) -> str:
    return v if v.startswith("«") else f"«{v}»"


class Ctx:
    """Подстановка значений в шаблоны с учётом рода слота и рода пользователя."""

    def __init__(self, dom: Domain, ent: dict, user_gender: str):
        self.dom, self.ent, self.ug = dom, ent, user_gender
        self.slot = f"{dom.slot_nom} {ent['q']}"
        self.slot_acc = f"{dom.slot_acc} {ent['q']}"

    def fill(self, tpl: str, **kw) -> str:
        g = self.dom.gender
        fields = dict(self.ent)
        fields.update(slot=self.slot, Slot=cap(self.slot), slot_acc=self.slot_acc,
                      izmenen=SLOT_FORMS["izmenen"][g])
        for k, v in kw.items():
            fields[k] = v
        if "reason" in fields and fields["reason"] is not None:
            fields["Reason"] = cap(fields["reason"])
        text = tpl.format(**fields)
        return cap(resolve_gender(text, self.ug))


def _reason_text(ctx: Ctx, tpl: str) -> str:
    return resolve_gender(tpl.format(**ctx.ent), ctx.ug)


def _assign_changes(rng: random.Random, count: int) -> list[str]:
    """Сбалансированное распределение видов изменений: каждые три подряд — разные виды."""
    out: list[str] = []
    while len(out) < count:
        block = list(CHANGE_TYPES)
        rng.shuffle(block)
        if out and block[0] == out[-1]:
            block.reverse()
        out.extend(block)
    return out[:count]


def _chain_events(rng, dom: Domain, ctx: Ctx, values: list[str], changes: list[str],
                  used_reasons: set[str], slot_tag: str, reserve: set[str] | None = None,
                  ellipsis: float = 0.0) -> list[dict]:
    """События записей одной цепочки: первая запись и n-1 изменений."""
    events = []
    plain = [r for r in dom.reasons]
    for i, v in enumerate(values):
        if i == 0:
            u = ctx.fill(rng.choice(dom.first_user), v=v)
            a = ctx.fill(rng.choice(ACK_FIRST), v=v)
            events.append(dict(kind="record", slot=slot_tag, version=1, change="first", reason=None,
                               turns=[("u", u), ("a", a)], value=v, value_turn=0))
            continue
        ch = changes[i - 1]
        old = values[i - 1]
        pool = dom.corr_reasons if ch == "correction" else plain
        cands = []
        for tpl in pool:
            r = _reason_text(ctx, tpl)
            if r in used_reasons or (reserve and r in reserve):
                continue
            if ch == "implicit" and CHANGE_MARKERS.search(r):
                continue
            cands.append(r)
        if not cands:  # для слотов-помех допускаем повтор причины
            cands = [_reason_text(ctx, t) for t in pool
                     if not (ch == "implicit" and CHANGE_MARKERS.search(_reason_text(ctx, t)))
                     and not (reserve and _reason_text(ctx, t) in reserve)]
        reason = rng.choice(cands)
        used_reasons.add(reason)
        two_turn = ch != "correction" and dom.ellipsis_agent and rng.random() < ellipsis
        if two_turn:
            # запись в два хода: событие, уточняющий вопрос агента, короткий ответ со значением
            # подтверждение не повторяет название слота: связь с сущностью видна из соседних ходов
            if ch == "explicit":
                u0 = ctx.fill("{Reason}, поэтому {slot_acc} нужно поменять.", reason=reason)
                a = ctx.fill(rng.choice(["Понятно, теперь {new}.", "Хорошо, меняю на {new}."]), new=v)
            else:
                u0 = ctx.fill("{Reason}.", reason=reason)
                a = ctx.fill(rng.choice(["Записано: {new}.", "Хорошо, {new}."]), new=v)
            turns = [("u", u0), ("a", dom.ellipsis_agent), ("u", ctx.fill(dom.ellipsis_user, new=v)), ("a", a)]
            events.append(dict(kind="record", slot=slot_tag, version=i + 1, change=ch, reason=reason,
                               turns=turns, value=v, value_turn=2))
            continue
        if ch == "explicit":
            u = ctx.fill(rng.choice(dom.explicit_user), reason=reason, old=old, new=v)
            a = ctx.fill(rng.choice(ACK_EXPLICIT), old=old, new=v)
        elif ch == "implicit":
            u = ctx.fill(rng.choice(dom.implicit_user), reason=reason, new=v)
            a = ctx.fill(rng.choice(ACK_IMPLICIT), new=v)
        else:
            u = ctx.fill(rng.choice(dom.correction_user), reason=reason, old=old, new=v)
            a = ctx.fill(rng.choice(ACK_CORRECTION), old=old, new=v)
        events.append(dict(kind="record", slot=slot_tag, version=i + 1, change=ch, reason=reason,
                           turns=[("u", u), ("a", a)], value=v, value_turn=0))
    return events


NOISE = {
    # уровень 0 — первая версия генератора: два упоминания вне записей, без названия сущности
    0: dict(strays=lambda n: 2, stray_entity=0.0, ellipsis=0.0),
    # уровень 1 — после проверки пилотного набора поверхностными эвристиками (п. 2.3)
    1: dict(strays=lambda n: max(2, n // 2 + 1), stray_entity=0.6, ellipsis=0.6),
}


def generate_scenario(sid: str, domain: str, n: int, m: int, extra: str, seed: int,
                      noise: int = 1) -> dict:
    """Один сценарий. extra: none | rejected | forget_soft | forget_ban."""
    nz = NOISE[noise]
    rng = random.Random(seed)
    dom = DOMAINS[domain]
    ug = rng.choice(["m", "f"])
    ents = rng.sample(dom.entities, m + 1)
    target_ent, other_ents = ents[0], ents[1:]
    tctx = Ctx(dom, target_ent, ug)

    used_values: set[str] = set()
    tvals = dom.sample_values(rng, n, used_values)
    used_values |= set(tvals)
    tchanges = _assign_changes(rng, n - 1)

    # причины для целевой цепочки выбираются первыми и затем не повторяются
    used_reasons: set[str] = set()
    target_events = _chain_events(rng, dom, tctx, tvals, tchanges, used_reasons, "target",
                                  ellipsis=nz["ellipsis"])
    target_reasons = {e["reason"] for e in target_events if e["reason"]}

    others = []
    for oi, oe in enumerate(other_ents):
        octx = Ctx(dom, oe, ug)
        L = rng.choice([2, 3])
        ov = dom.sample_values(rng, L, used_values)
        used_values |= set(ov)
        och = [rng.choice(CHANGE_TYPES) for _ in range(L - 1)]
        evs = _chain_events(rng, dom, octx, ov, och, set(used_reasons), f"other{oi}", reserve=target_reasons,
                            ellipsis=nz["ellipsis"])
        others.append(dict(slot=octx.slot, entity=oe["E"], chain=[dict(value=e["value"], change=e["change"],
                                                                           reason=e["reason"]) for e in evs],
                           events=evs))

    # --- сегменты между записями целевой цепочки: S_0, T1, S_1, ..., Tn, S_n
    segments: list[list[dict]] = [[] for _ in range(n + 1)]
    for o in others:
        idx = sorted(rng.randint(0, n) for _ in o["events"])
        for e, s in zip(o["events"], idx):
            segments[s].append(e)

    rejected = None
    forget = None
    if extra == "rejected":
        i = rng.randint(1, n)        # предложение звучит, пока действует v_i
        w = dom.sample_values(rng, 1, used_values)[0]
        used_values.add(w)
        cur = tvals[i - 1]
        turns = [("u", tctx.fill(dom.rejected_user, w=w)),
                 ("a", tctx.fill("Можно. Поменять на {w}?", w=w)),
                 ("u", tctx.fill("Нет, всё-таки оставим {cur}.", cur=cur)),
                 ("a", tctx.fill("Хорошо, оставляем {cur}.", cur=cur))]
        segments[i].append(dict(kind="rejected", slot="target", value=w, turns=turns))
        rejected = dict(value=w, while_version=i)
    elif extra in ("forget_soft", "forget_ban"):
        j = rng.randint(1, n - 1)
        old = tvals[j - 1]
        if extra == "forget_soft":
            turns = [("u", tctx.fill("Кстати, вариант {old} можно забыть — он больше не понадобится.", old=old)),
                     ("a", "Хорошо.")]
        else:
            turns = [("u", tctx.fill("И ещё: вариант {old} удалите из записей и больше не называйте, "
                                     "даже если я [сам|сама] о нём спрошу, — " + dom.forget_tail + ".", old=old)),
                     ("a", "Хорошо, этот вариант удалён и называться не будет.")]
        s = rng.randint(j + 1, n)    # только после того, как v_j перестала действовать
        segments[s].append(dict(kind="forget", slot="target", version=j, turns=turns))
        forget = dict(version=j, mode="ban" if extra == "forget_ban" else "soft")

    strays = []
    forg = forget["version"] if forget else None
    n_str = nz["strays"](n)
    stray_tpls = list(dom.stray_user)
    ent_tpls = list(dom.stray_entity)
    rng.shuffle(stray_tpls)
    rng.shuffle(ent_tpls)
    used_tpl: set[str] = set()
    for t in range(n_str):
        # чередуем упоминание устаревшей версии (после её смены) и будущей (до её записи)
        back = (t % 2 == 0)
        cands = [a for a in range(1, n) if a != forg] if back else [b for b in range(2, n + 1) if b != forg]
        taken = {(v, bb) for v, _, bb in strays}
        cands = [c for c in cands if (c, back) not in taken] or cands
        if not cands:
            continue
        ver = rng.choice(cands)
        seg = rng.randint(ver + 1, n) if back else rng.randint(0, ver - 1)
        use_ent = bool(ent_tpls) and rng.random() < nz["stray_entity"]
        first = ent_tpls if use_ent else stray_tpls
        pool = [x for x in first if x not in used_tpl] or [x for x in stray_tpls + ent_tpls if x not in used_tpl]
        if not pool:
            break
        tpl = pool[0]
        used_tpl.add(tpl)
        x = tvals[ver - 1]
        segments[seg].append(dict(kind="stray", slot="target", version=ver,
                                  turns=[("u", tctx.fill(tpl, x=x)), ("a", rng.choice(ACK_STRAY))]))
        strays.append((ver, seg, back))

    # посторонние ходы: промежутки после версий и блок, сдвигаемый при выборе позиции
    fill_pool = list(dom.filler)
    rng.shuffle(fill_pool)
    gaps = []
    for i in range(1, n):
        g = rng.choice([0, 1])
        gaps.append(g)
        for _ in range(g):
            if fill_pool:
                fu, fa = fill_pool.pop()
                segments[i].append(dict(kind="filler", turns=[("u", fu), ("a", fa)]))
    gaps.append(0)
    n_pos = min(6, len(fill_pool))
    pos_filler = [dict(kind="filler", turns=[("u", fu), ("a", fa)]) for fu, fa in fill_pool[:n_pos]]

    region: list[dict] = []
    for s in range(n + 1):
        seg = segments[s]
        rng.shuffle(seg)
        # записи одной цепочки-помехи внутри сегмента должны идти по порядку
        seg = _stable_order(seg)
        region.extend(seg)
        if s < n:
            region.append(target_events[s])

    ent_list = [e[dom.list_form] for e in ents]
    rng.shuffle(ent_list)
    intro = [("u", cap(dom.intro_user.format(list=join_ru(ent_list)))), ("a", dom.intro_agent)]

    scen = dict(
        id=sid, domain=domain, vtype=dom.vtype, n=n, m=m, extra=extra, seed=seed, user_gender=ug,
        slot=tctx.slot, entity=target_ent["E"],
        chain=[dict(value=e["value"], change=e["change"], reason=e["reason"]) for e in target_events],
        others=[{k: v for k, v in o.items() if k != "events"} for o in others],
        rejected=rejected, forget=forget, strays=[dict(version=v, segment=sg, back=b) for v, sg, b in strays],
        gaps=gaps, intro=intro, region=region, pos_filler=pos_filler,
    )
    scen["questions"] = build_questions(scen, rng)
    return scen


def _stable_order(seg: list[dict]) -> list[dict]:
    """Восстанавливает порядок версий внутри каждого слота-помехи, не трогая остальное."""
    by_slot: dict[str, list[dict]] = {}
    for e in seg:
        if e.get("kind") == "record":
            by_slot.setdefault(e["slot"], []).append(e)
    for lst in by_slot.values():
        lst.sort(key=lambda e: e["version"])
    it = {k: iter(v) for k, v in by_slot.items()}
    return [next(it[e["slot"]]) if e.get("kind") == "record" else e for e in seg]


# ---------------------------------------------------------------- вопросы
def build_questions(s: dict, rng: random.Random) -> list[dict]:
    dom = DOMAINS[s["domain"]]
    g = dom.gender
    ug = s["user_gender"]
    n = s["n"]
    vals = [c["value"] for c in s["chain"]]
    slot = s["slot"]
    F = {k: v[g] for k, v in SLOT_FORMS.items()}

    def R(text: str) -> str:
        return cap(resolve_gender(text, ug))

    qs: list[dict] = []

    def add(k, sigma, text, direction=None):
        j = n - k
        ch_next = s["chain"][j]["change"] if j < n else None   # вид изменения, завершившего v_j
        qs.append(dict(k=k, sigma=sigma, direction=direction, text=R(text), gold_version=j,
                       change_of_version=s["chain"][j - 1]["change"], change_after=ch_next))

    add(0, "direct", f"{F['kakoy']} сейчас {slot}?")
    for k in range(1, n):
        j = n - k
        direction = rng.choice(["start", "end"])
        if direction == "start":
            add(k, "ordinal", f"{F['kakoy']} {slot} {F['byl']} {F['ukazan']} {ordinal_instr(j, g)} по счёту? "
                              f"Учитывай все варианты, которые я [указывал|указывала], в том числе ошибочные.", "start")
        else:
            add(k, "ordinal", f"{F['kakoy']} {F['byl']} {slot} {CHANGES_AGO[k]} назад? "
                              f"Исправления ошибок тоже считай изменениями.", "end")
        if k == 1:
            add(k, "relative", f"{F['kakoy']} {F['byl']} {F['prev']} {slot}?")
        if k == n - 1:
            add(k, "relative", f"{F['kakoy']} {F['byl']} {F['orig']} {slot}?")
        add(k, "event_value", f"{F['kakoy']} {slot} {F['byl']} до варианта {quote(vals[j])}?")
        reason = s["chain"][j]["reason"]
        add(k, "event_desc", f"{F['kakoy']} {slot} {F['byl']} {F['ukazan']} до того, как я "
                             f"[сказал|сказала], что {reason}?")

    forg = s["forget"]
    out = []
    for q in qs:
        q["gold"] = vals[q["gold_version"] - 1]
        q["qtype"] = "depth"
        if forg and q["gold_version"] == forg["version"]:
            if forg["mode"] == "soft":
                continue                       # эталон неоднозначен — вопрос не задаётся
            q["gold"] = None                   # ⊥: пользователь запретил называть значение
            q["qtype"] = "forgotten"
        out.append(q)

    cand = [j for j in range(1, n) if not (forg and j == forg["version"])]
    pj = rng.choice(cand)
    out.append(dict(k=None, sigma="false_premise", direction=None, qtype="false_premise",
                    text=R(f"{cap(slot)} ведь {vals[pj - 1]}, верно? Назови {F['cur_acc']} {_slot_acc(s)}."),
                    premise_version=pj, gold_version=n, gold=vals[-1],
                    change_of_version=s["chain"][-1]["change"], change_after=None))
    for i, q in enumerate(out, 1):
        q["qid"] = f"{s['id']}-Q{i:02d}"
    return out


def _slot_acc(s: dict) -> str:
    dom = DOMAINS[s["domain"]]
    q = s["slot"][len(dom.slot_nom) + 1:]
    return f"{dom.slot_acc} {q}"
