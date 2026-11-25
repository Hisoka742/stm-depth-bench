"""Проверка формулировки системной инструкции для формата «список фактов».

    python scripts/build_prompt2_set.py

Строит data/main_bank_prompt2: те же входы формата «факты», что в data/main_bank, но в системной
инструкции правило о действующем значении явно ограничено просьбами что-то сделать, и добавлено
предложение о вопросах про прежние значения. Повод — в основном прогоне gpt-6.1-terra в формате
«факты» примерно на трети вопросов о прежних версиях называла текущее значение: она применяла
правило «если клиент называет устаревшее значение, используй действующее» к вопросам вида
«какое значение было до варианта X?». Остальные модели так не делали.
"""
from __future__ import annotations

import json
import os
import shutil
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)
from stmbench.render import SYSTEM_FACTS  # noqa: E402

OLD = "если клиент называет устаревшее значение, используй действующее. "
NEW = ("если в такой просьбе клиент называет устаревшее значение, используй действующее. "
       "Если клиент спрашивает о прежних значениях, назови то значение, о котором спрашивают. ")


def main():
    assert OLD in SYSTEM_FACTS
    system = SYSTEM_FACTS.replace(OLD, NEW)
    src, dst = os.path.join(ROOT, "data", "main_bank"), os.path.join(ROOT, "data", "main_bank_prompt2")
    os.makedirs(dst, exist_ok=True)
    shutil.copy(os.path.join(src, "scenarios.jsonl"), os.path.join(dst, "scenarios.jsonl"))
    n = 0
    with open(os.path.join(src, "items.jsonl"), encoding="utf-8") as fin, \
            open(os.path.join(dst, "items.jsonl"), "w", encoding="utf-8") as fout:
        for line in fin:
            it = json.loads(line)
            if it["fmt"] != "facts":
                continue
            assert it["messages"][0]["content"] == SYSTEM_FACTS
            it["messages"][0]["content"] = system
            fout.write(json.dumps(it, ensure_ascii=False) + "\n")
            n += 1
    print(f"входов: {n}\n{system}")


if __name__ == "__main__":
    main()
