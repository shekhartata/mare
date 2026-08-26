#!/usr/bin/env python3
"""Seed data, build hierarchy + RAG chunks, probe capabilities, create indexes."""

from __future__ import annotations

import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
STEPS = [
    "scripts/seed.py",
    "scripts/build_hierarchy.py",
    "scripts/build_rag_index.py",
    "scripts/probe_capabilities.py",
    "scripts/create_indexes.py",
]


def main() -> None:
    for step in STEPS:
        print(f"\n=== {step} ===")
        subprocess.check_call([sys.executable, str(ROOT / step)], cwd=ROOT)


if __name__ == "__main__":
    main()
