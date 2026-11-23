"""Сборка набора сценариев по конфигурации.

    python scripts/build_set.py configs/pilot.yaml
    python scripts/build_set.py configs/main.yaml

Результат: data/<name>/scenarios.jsonl (сценарии с вопросами и эталонами),
data/<name>/items.jsonl (входы моделей), data/<name>/report.txt (проверка разметки).
"""
from __future__ import annotations

import itertools
import json
import os
import sys

import yaml

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from stmbench.generator import generate_scenario  # noqa: E402
from stmbench.render import render_items  # noqa: E402
from stmbench.validate import validate  # noqa: E402


def plan(cfg: dict) -> list[dict]:
    """Список сценариев: полный перебор сетки n × m × домен × повтор, доп. события по кругу."""
    rows = []
    for block in cfg["blocks"]:
        extras = block["extras"]
        cells = list(itertools.product(block["n"], block["m"], cfg["domains"], range(block.get("replicates", 1))))
        for i, (n, m, dom, r) in enumerate(cells):
            rows.append(dict(n=n, m=m, domain=dom, replicate=r, extra=extras[i % len(extras)],
                             positions=block.get("positions", ["start", "middle", "end"]),
                             block=block["name"]))
    # для пилота позиция может чередоваться, а не перебираться полностью
    if cfg.get("rotate_positions"):
        pos = ["start", "middle", "end"]
        for i, r in enumerate(rows):
            r["positions"] = [pos[i % 3]]
    return rows


def main(path: str):
    with open(path, encoding="utf-8") as f:
        cfg = yaml.safe_load(f)
    root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    out_dir = os.path.join(root, "data", cfg["name"])
    os.makedirs(out_dir, exist_ok=True)
    rows = plan(cfg)
    scen_f = open(os.path.join(out_dir, "scenarios.jsonl"), "w", encoding="utf-8")
    item_f = open(os.path.join(out_dir, "items.jsonl"), "w", encoding="utf-8")
    report = []
    n_items = n_q = 0
    for i, r in enumerate(rows, 1):
        sid = f"{cfg['prefix']}{i:03d}"
        seed = cfg["seed"] * 100000 + i
        # при нарушении проверок сценарий перегенерируется со следующим зерном
        for attempt in range(50):
            s = generate_scenario(sid, r["domain"], r["n"], r["m"], r["extra"], seed + attempt * 7919,
                                  noise=cfg.get("noise", 1))
            errs = validate(s)
            if not errs:
                break
            report.append(f"{sid} попытка {attempt}: " + "; ".join(errs))
        else:
            raise RuntimeError(f"{sid}: не удалось получить корректный сценарий")
        s["block"] = r["block"]
        s["positions"] = r["positions"]
        scen_f.write(json.dumps(s, ensure_ascii=False) + "\n")
        n_q += len(s["questions"])
        for it in render_items(s, positions=r["positions"], with_facts=cfg.get("facts", True)):
            item_f.write(json.dumps(it, ensure_ascii=False) + "\n")
            n_items += 1
    scen_f.close()
    item_f.close()
    summary = f"сценариев: {len(rows)}, вопросов: {n_q}, входов моделей: {n_items}"
    with open(os.path.join(out_dir, "report.txt"), "w", encoding="utf-8") as f:
        f.write(summary + "\n" + "\n".join(report) + "\n")
    print(summary)
    print(f"перегенераций из-за проверок: {len(report)}")


if __name__ == "__main__":
    main(sys.argv[1])
