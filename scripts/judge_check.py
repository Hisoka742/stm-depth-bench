"""Проверка надёжности LLM-судьи без ручной разметки (п. 2.4 ВКР).

    python scripts/judge_check.py data/pilot --judge <id модели> [--n 300]
    python scripts/judge_check.py data/pilot --dry          # только построить тестовые ответы

Тест 1 (перефразировки). Для случайных вопросов значение одной из версий цепочки
переписывается в другой форме (другие сокращения, падеж, формат даты, суммы, телефона,
времени, ответ внутри предложения). Судья должен указать именно эту версию. Берётся
не только эталон, но и другие версии, чтобы проверить, что судья не тянется к эталону.
Отдельно проверяется, что на значение, которого нет в диалоге, судья отвечает NONE.
Тест 2 (согласие с точной проверкой). На ответах моделей, уже классифицированных точной
проверкой (results/<набор>/*__scored.jsonl), судья должен выбрать ту же версию.
"""
from __future__ import annotations

import argparse
import glob
import json
import os
import random
import re
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)
from stmbench.domains import DOMAINS  # noqa: E402
from stmbench.judge import judge_prompt, parse_judge  # noqa: E402
from stmbench.openrouter import NO_REASONING, chat  # noqa: E402
from stmbench.scoring import exact_match  # noqa: E402

MONTHS = {"декабря": "12", "января": "01"}
WRAP = ["{p}", "Ответ: {p}.", "Насколько я помню, это {p}.", "Вы указывали {p}.", "Это был вариант {p}."]


def paraphrases(value: str, vtype: str) -> list[str]:
    if vtype == "addr":
        street, num = re.match(r"ул\. (\S+), (\d+)", value).groups()
        loc = street[:-2] + "ой"
        return [f"улица {street}, дом {num}", f"{street} ул., д. {num}", f"на {loc}, {num}",
                f"{street}, {num}", f"ул.{street} д.{num}"]
    if vtype == "date":
        d, m = value.split()
        return [f"{int(d):02d}.{MONTHS[m]}", f"{d}-го {m}", f"{d}/{MONTHS[m]}", f"на {d} {m}"]
    if vtype == "money":
        n = int(value.split()[0])
        return [f"{n} тыс. руб.", f"{n * 1000} ₽", f"{n} тысяч рублей", f"{n} 000 руб.", f"{n}к"]
    if vtype == "phone":
        d = re.sub(r"\D", "", value)
        return [f"8 ({d[1:4]}) {d[4:7]}-{d[7:9]}-{d[9:]}", f"+{d}", f"8-{d[1:4]}-{d[4:7]}-{d[7:9]}-{d[9:]}"]
    if vtype == "time":
        h, mm = value.split(":")
        out = [f"{h}.{mm}", f"{int(h):02d}:{mm}", f"в {h} ч {mm} мин" if mm != "00" else f"в {h}:00 ровно"]
        if int(h) > 12:
            out.append(f"{int(h) - 12}:{mm} вечера" if mm != "00" else f"в {int(h) - 12} вечера")
        return out
    if vtype == "card":
        d = value[-4:]
        return [f"карта, оканчивающаяся на {d}", f"…{d}", f"карта {d}", f"карта **** {d}"]
    raise ValueError(vtype)


def absent_value(s: dict, rng) -> str:
    dom = DOMAINS[s["domain"]]
    used = {c["value"] for c in s["chain"]} | {c["value"] for o in s["others"] for c in o["chain"]}
    if s.get("rejected"):
        used.add(s["rejected"]["value"])
    used = {dom.vt.canon(v) for v in used}
    # половина отсутствующих значений — близкие к значениям цепочки (проверка «притягивания»)
    if rng.random() < 0.5:
        near = [v for c in s["chain"] for v in dom.vt.near(rng, c["value"]) if dom.vt.canon(v) not in used]
        if near:
            return rng.choice(near)
    return dom.sample_values(rng, 1, used)[0]


def build_tests(set_dir, n, seed=0):
    rng = random.Random(seed)
    scen = [json.loads(x) for x in open(os.path.join(set_dir, "scenarios.jsonl"), encoding="utf-8")]
    pairs = [(s, q) for s in scen for q in s["questions"] if q["qtype"] == "depth"]
    tests = []
    for _ in range(n):
        s, q = rng.choice(pairs)
        if rng.random() < 0.3:
            v = absent_value(s, rng)
            expect = "NONE"
        else:
            j = q["gold_version"] if rng.random() < 0.5 else rng.randint(1, s["n"])
            v = s["chain"][j - 1]["value"]
            expect = f"V{j}"
        p = rng.choice(paraphrases(v, s["vtype"]))
        ans = rng.choice(WRAP).format(p=p)
        tests.append(dict(sid=s["id"], qid=q["qid"], answer=ans, expect=expect,
                          exact=exact_match(ans, s)["label"]))
    return scen, tests


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("set_dir")
    ap.add_argument("--judge")
    ap.add_argument("--n", type=int, default=300)
    ap.add_argument("--dry", action="store_true")
    args = ap.parse_args()
    scen, tests = build_tests(args.set_dir, args.n)
    smap = {s["id"]: s for s in scen}
    qmap = {q["qid"]: q for s in scen for q in s["questions"]}
    exact_ok = sum(t["exact"] == t["expect"] for t in tests if t["expect"] != "NONE")
    n_pos = sum(t["expect"] != "NONE" for t in tests)
    abs_ok = sum(t["exact"] == "NONE" for t in tests if t["expect"] == "NONE")
    print(f"тестовых ответов: {len(tests)}; извлечение кодом узнаёт {exact_ok} из {n_pos} перефразировок "
          f"и {abs_ok} из {len(tests) - n_pos} отсутствующих значений; ошибок извлечения: "
          f"{sum(t['exact'] is not None and t['exact'] != t['expect'] for t in tests)}")
    out_path = os.path.join(set_dir_results(args.set_dir), "judge_check.jsonl")
    if args.dry or not args.judge:
        for t in tests[:10]:
            print(t)
        return
    with open(out_path, "w", encoding="utf-8") as f:
        for t in tests:
            s, q = smap[t["sid"]], qmap[t["qid"]]
            if t["exact"] is None:
                msgs, mapping = judge_prompt(s, q, t["answer"])
                r = chat(args.judge, msgs, temperature=0.0, max_tokens=64, extra=NO_REASONING)
                t["judge"] = parse_judge(r["content"], mapping)
            else:
                t["judge"] = None
            t["final"] = t["exact"] if t["exact"] is not None else t["judge"]
            f.write(json.dumps(t, ensure_ascii=False) + "\n")
    for name, sub in (("все", tests), ("значения из диалога", [t for t in tests if t["expect"] != "NONE"]),
                      ("отсутствующие значения", [t for t in tests if t["expect"] == "NONE"])):
        ok = sum(t["final"] == t["expect"] for t in sub)
        by_code = [t for t in sub if t["exact"] is not None]
        by_judge = [t for t in sub if t["exact"] is None]
        jok = sum(t["final"] == t["expect"] for t in by_judge)
        print(f"тест 1, {name}: верно {ok} из {len(sub)} ({ok / max(1, len(sub)):.3f}); код решил {len(by_code)}, "
              f"судья — {len(by_judge)}, из них верно {jok}")
    # тест 2: согласие с точной проверкой на ответах моделей
    agree = tot = 0
    for path in glob.glob(os.path.join(set_dir_results(args.set_dir), "*__scored.jsonl")):
        if "mock__" in path:
            continue
        rows = [json.loads(x) for x in open(path, encoding="utf-8")]
        res = {json.loads(x)["item_id"]: json.loads(x) for x in open(path.replace("__scored", ""), encoding="utf-8")}
        sample = [r for r in rows if r["method"] == "exact"]
        random.Random(1).shuffle(sample)
        for r in sample[:100]:
            s, q = smap[r["sid"]], qmap[r["qid"]]
            msgs, mapping = judge_prompt(s, q, res[r["item_id"]]["response"])
            lab = parse_judge(chat(args.judge, msgs, temperature=0.0, max_tokens=64, extra=NO_REASONING)["content"], mapping)
            agree += lab == r["label"]
            tot += 1
    if tot:
        print(f"тест 2: согласие судьи с точной проверкой {agree} из {tot} ({agree / tot:.3f})")


def set_dir_results(set_dir):
    p = os.path.join(ROOT, "results", os.path.basename(os.path.normpath(set_dir)))
    os.makedirs(p, exist_ok=True)
    return p


if __name__ == "__main__":
    main()
