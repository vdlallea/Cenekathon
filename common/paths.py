"""Centrale paden voor het team (zie SPEC.md, sectie Contracten).

Alle scripts importeren hun paden hier, zodat ze nergens hardcoded staan.

Gedeelde werkmap:
  - Server: /home/team6/data/work/  (SPEC.md noemt dit ~/data/work/)
  - Lokaal: <repo>/data/work/
Overschrijven kan met de env-var TEAM_DATA_WORK.
"""

import os
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent

_SERVER_WORK = Path("/home/team6/data/work")
_LOCAL_WORK = REPO_ROOT / "data" / "work"

DATA_WORK = Path(
    os.environ.get("TEAM_DATA_WORK")
    or (_SERVER_WORK if _SERVER_WORK.exists() else _LOCAL_WORK)
)

# Invoer (van A)
SAMPLE_PARQUET = DATA_WORK / "sample_20k.parquet"
SPINE_PARQUET = DATA_WORK / "spine.parquet"

# Uitvoer van B (tagging)
TAGS_PARQUET = DATA_WORK / "tags.parquet"
LABEL_SAMPLE_PARQUET = DATA_WORK / "label_sample_1500.parquet"
TEST_SET_PARQUET = DATA_WORK / "test_set_300.parquet"
CLAUDE_LABELS_PARQUET = DATA_WORK / "claude_labels_1500.parquet"

# Prompt en logs
TAGGING_DIR = REPO_ROOT / "tagging"
PROMPT_TXT = TAGGING_DIR / "llm_prompt_draft.txt"
LOG_DIR = DATA_WORK / "logs"  # bestaat al op de server (spine_full.log)
CLAUDE_USAGE_CSV = LOG_DIR / "claude_usage.csv"
CLAUDE_CHECKPOINT_JSONL = LOG_DIR / "claude_labels_checkpoint.jsonl"
