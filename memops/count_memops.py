"""Подсчёт вопросов с проверкой промежуточных состояний в наборе MemOps.

Использование:
    git clone https://github.com/MemTensor/MemOps      # коммит 312af65
    python count_memops.py MemOps/generated_result/2-evidence_conversation
"""
import collections
import glob
import json
import os
import sys

root = sys.argv[1]
files = sorted(glob.glob(os.path.join(root, "*.json")))
# второй режим оценки: "longitudinal_operation" (числа совпадают)
setting = "adjacent_operation"

n_dialogs = len(files)
n_questions = 0
by_type = collections.Counter()        # тип пробы (evaluation_type)
inter_by_type = collections.Counter()  # непустая проверка intermediate_state
num_updates = collections.Counter()    # значения update_chain.num_updates
n_chain_dialogs = 0

for path in files:
    with open(path, encoding="utf-8") as f:
        d = json.load(f)
    op = d["operation_type"]
    if op in ("Update", "TrajectoryOps"):
        n_chain_dialogs += 1
        chain = d["difficulty_knobs"]["update_chain"]
        num_updates[chain["num_updates"]] += 1
    for a in d["answer"]:
        if a["evaluation_setting"] != setting:
            continue
        n_questions += 1
        by_type[a["evaluation_type"]] += 1
        checks = a.get("diagnostic_checks") or {}
        if checks.get("intermediate_state"):
            inter_by_type[(op, a["evaluation_type"])] += 1

n_st = by_type["StateTrajectory"]
n_inter = sum(inter_by_type.values())
print(f"Диалогов: {n_dialogs}")
print(f"Вопросов в режиме {setting}: {n_questions}")
print(f"StateTrajectory: {n_st} ({100 * n_st / n_questions:.1f} %)")
print(f"С проверкой intermediate_state: {n_inter} "
      f"({100 * n_inter / n_questions:.1f} %)")
for (op, t), n in sorted(inter_by_type.items()):
    print(f"    {op} / {t}: {n}")
print(f"Сценариев Update и TrajectoryOps: {n_chain_dialogs}")
print(f"Значения num_updates: {dict(num_updates)}")
