"""Оценка ответов моделей (п. 2.4 ВКР).

    python scripts/score.py data/pilot results/pilot/<модель>.jsonl [--judge <id модели-судьи>]

1) точная проверка после нормализации; 2) для нерешённых ответов — LLM-судья (если указан;
его ответы кешируются в results/<набор>/judge__<судья>.jsonl). Печатает и сохраняет сводку:
точность по глубинам и способам задания глубины (макроусреднение по k), матрицу ответов M,
классы ошибок, долю утечек, долю принятых ложных предпосылок, долю ответов, решённых судьёй.
"""
from __future__ import annotations

import argparse
import json
import os
import sys
from collections import Counter, defaultdict

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)
from stmbench.judge import judge_prompt, parse_judge  # noqa: E402
from stmbench.openrouter import NO_REASONING, chat  # noqa: E402
from stmbench.scoring import error_class, exact_match, leaked  # noqa: E402
from stmbench.solvers import macro  # noqa: E402


def load_jsonl(path):
    if not os.path.exists(path):
        return []
    with open(path, encoding="utf-8") as f:
        return [json.loads(x) for x in f if x.strip()]


def slug(model_id: str) -> str:
    return model_id.replace("/", "__").replace(":", "_")


def classify_all(set_dir, res_path, judge_model=None):
    scen = {s["id"]: s for s in load_jsonl(os.path.join(set_dir, "scenarios.jsonl"))}
    qmap = {q["qid"]: (s, q) for s in scen.values() for q in s["questions"]}
    # последний успешный ответ на каждый вход
    res = {}
    for r in load_jsonl(res_path):
        if r.get("error") is None:
            res[r["item_id"]] = r
    jpath = None
    jcache = {}
    if judge_model:
        jpath = os.path.join(os.path.dirname(res_path), f"judge__{slug(judge_model)}.jsonl")
        jcache = {(j["qid"], j["answer"]): j for j in load_jsonl(jpath)}
    jf = open(jpath, "a", encoding="utf-8") if jpath else None
    rows = []
    for r in res.values():
        s, q = qmap[r["qid"]]
        ans = r["response"]
        em = exact_match(ans, s)
        label, method = em["label"], em["method"]
        if label is None and judge_model:
            key = (q["qid"], ans)
            if key not in jcache:
                msgs, mapping = judge_prompt(s, q, ans)
                out = chat(judge_model, msgs, temperature=0.0, max_tokens=64, extra=NO_REASONING)
                jrec = dict(qid=q["qid"], answer=ans, raw=out["content"], label=parse_judge(out["content"], mapping))
                jcache[key] = jrec
                jf.write(json.dumps(jrec, ensure_ascii=False) + "\n")
                jf.flush()
            label, method = jcache[key]["label"], "judge"
        cls = error_class(label, q, s) if label not in (None, "MULTIPLE", "UNPARSED") else "unresolved"
        rows.append(dict(item_id=r["item_id"], qid=q["qid"], sid=s["id"], fmt=r["fmt"], position=r["position"],
                         n=s["n"], m=s["m"], k=q.get("k"), sigma=q["sigma"], qtype=q["qtype"],
                         direction=q.get("direction"), change=q.get("change_of_version"),
                         change_after=q.get("change_after"), gold_version=q.get("gold_version"),
                         label=label, method=method, cls=cls, leak=leaked(label, ans, s), domain=s["domain"],
                         extra=s["extra"]))
    if jf:
        jf.close()
    return rows


def summarize(rows):
    out = {}
    depth = [r for r in rows if r["qtype"] == "depth"]
    out["n_answers"] = len(rows)
    out["share_judge"] = sum(r["method"] == "judge" for r in rows) / max(1, len(rows))
    out["share_unresolved"] = sum(r["cls"] == "unresolved" for r in rows) / max(1, len(rows))
    for fmt in sorted({r["fmt"] for r in depth}):
        d = [r for r in depth if r["fmt"] == fmt]
        rec = lambda rs: [(r["n"], r["k"], r["cls"] == "correct") for r in rs]  # noqa: E731
        o = out.setdefault(fmt, {})
        o["acc_macro"] = macro(rec(d))
        o["by_n"] = {n: macro(rec([r for r in d if r["n"] == n])) for n in sorted({r["n"] for r in d})}
        o["by_sigma"] = {sg: macro(rec([r for r in d if r["sigma"] == sg])) for sg in sorted({r["sigma"] for r in d})}
        o["by_nk"] = {f"{n},{k}": sum(r["cls"] == "correct" for r in d if r["n"] == n and r["k"] == k) /
                      max(1, sum(1 for r in d if r["n"] == n and r["k"] == k))
                      for n, k in sorted({(r["n"], r["k"]) for r in d})}
        o["by_m"] = {m: macro(rec([r for r in d if r["m"] == m])) for m in sorted({r["m"] for r in d})}
        o["by_position"] = {p: macro(rec([r for r in d if r["position"] == p]))
                            for p in sorted({str(r["position"]) for r in d}) if p != "None"} if fmt == "log" else {}
        o["by_change"] = {c: macro(rec([r for r in d if r["change"] == c])) for c in sorted({r["change"] for r in d})}
        o["error_classes"] = dict(Counter(r["cls"] for r in d))
        # матрица ответов M[n][k][j]: доля ответов «версия v_j» на вопросы глубины k
        M = defaultdict(lambda: defaultdict(Counter))
        for r in d:
            if r["label"] and r["label"].startswith("V"):
                M[r["n"]][r["k"]][int(r["label"][1:])] += 1
            else:
                M[r["n"]][r["k"]]["other"] += 1
        o["matrix"] = {n: {k: {str(j): c / sum(cnt.values()) for j, c in cnt.items()} for k, cnt in ks.items()}
                       for n, ks in M.items()}
    fp = [r for r in rows if r["qtype"] == "false_premise"]
    if fp:
        out["false_premise"] = dict(correct=sum(r["cls"] == "correct" for r in fp) / len(fp),
                                    accepted_premise=sum(r["cls"] == "accepted_premise" for r in fp) / len(fp))
    fg = [r for r in rows if r["qtype"] == "forgotten"]
    if fg:
        out["forgotten"] = dict(refusal=sum(r["cls"] == "correct" for r in fg) / len(fg),
                                leak=sum(r["cls"] == "leak" for r in fg) / len(fg))
    withf = [r for r in rows if r["extra"].startswith("forget")]
    if withf:
        out["leak_rate_all_answers"] = sum(r["leak"] for r in withf) / len(withf)
    return out


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("set_dir")
    ap.add_argument("results")
    ap.add_argument("--judge")
    args = ap.parse_args()
    rows = classify_all(args.set_dir, args.results, args.judge)
    summ = summarize(rows)
    base = os.path.splitext(args.results)[0]
    with open(base + "__scored.jsonl", "w", encoding="utf-8") as f:
        for r in rows:
            f.write(json.dumps(r, ensure_ascii=False) + "\n")
    with open(base + "__summary.json", "w", encoding="utf-8") as f:
        json.dump(summ, f, ensure_ascii=False, indent=1)
    print(json.dumps({k: v for k, v in summ.items() if k not in ("log", "facts")}, ensure_ascii=False, indent=1))
    for fmt in ("log", "facts"):
        if fmt in summ:
            o = summ[fmt]
            print(f"[{fmt}] точность (макро по k): {o['acc_macro']:.3f}; по n: "
                  + ", ".join(f"{n}: {v:.3f}" for n, v in o["by_n"].items()))
            print("   по способам: " + ", ".join(f"{k}: {v:.3f}" for k, v in o["by_sigma"].items()))
            print("   классы: " + str(o["error_classes"]))


if __name__ == "__main__":
    main()
