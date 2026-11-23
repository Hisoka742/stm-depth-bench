"""Расход и остаток средств по ключу OpenRouter (ключ — в OPENROUTER_API_KEY).

    python scripts/balance.py
"""
from __future__ import annotations

import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from stmbench.openrouter import key_info  # noqa: E402

d = key_info()
print(f"израсходовано: {d.get('usage', 0):.4f} $")
if d.get("limit") is not None:
    print(f"лимит: {d['limit']} $, осталось: {d.get('limit_remaining')} $")
