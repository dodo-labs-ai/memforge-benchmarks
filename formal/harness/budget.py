"""The stage's running token total, against its cap.

Everything the stage's models were paid for counts: agent runs and probes as input plus
output, where the reported input already holds the cached input, so cached tokens count
once; MemForge's generation calls as prompt plus completion tokens. Embedding tokens are a
separate line and do not count, as the cap names only generation and agent tokens.
"""

from __future__ import annotations

import json
from pathlib import Path

from ..common import STAGE0

TOKEN_CAP = 30_000_000
SCREEN_ATTEMPTS = STAGE0 / "screen" / "attempts.jsonl"
PROBES = STAGE0 / "probes.jsonl"
SYNC_USAGE = STAGE0 / "sync" / "generation_usage.json"


def _rows(path: Path) -> list[dict]:
    if not path.exists():
        return []
    return [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines() if line.strip()]


def spent() -> dict:
    screen = sum(row["tokens"]["total"] for row in _rows(SCREEN_ATTEMPTS))
    probes = sum(row["tokens"]["total"] for row in _rows(PROBES))
    usage = json.loads(SYNC_USAGE.read_text(encoding="utf-8")) if SYNC_USAGE.exists() else {}
    generation = int(usage.get("prompt_tokens", 0)) + int(usage.get("completion_tokens", 0))
    return {"screen": screen, "probes": probes, "memforge_generation": generation, "total": screen + probes + generation, "cap": TOKEN_CAP}


def total() -> int:
    return spent()["total"]
