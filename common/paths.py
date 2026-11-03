"""Centrale paden voor het team (zie SPEC.md, sectie Contracten).
Wijzig dit alleen via een PR die in de groep is aangekondigd."""

import os
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]

# Werkmap afhandeling (Server vs Lokaal)
_SERVER_WORK = Path("/home/team6/data/work")
_LOCAL_WORK = ROOT / "data" / "work"

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

# Prompt (B)
TAGGING_DIR = ROOT / "tagging"
PROMPT_TXT = TAGGING_DIR / "llm_prompt_draft.txt"

# Eindbestanden (klein, wel in git) (Slice C & D)
FINAL_DIR = ROOT / "data" / "final"
CARDS_DIR = FINAL_DIR / "cards"
COMPANY_QUARTER = FINAL_DIR / "company_quarter.parquet"
PEERS = FINAL_DIR / "peers.parquet"

# Stubs: nepdata voor als de echte bestanden nog niet bestaan (Slice D)
STUB_DIR = ROOT / "app" / "stubs"
STUB_COMPANY_QUARTER = STUB_DIR / "company_quarter.parquet"
STUB_PEERS = STUB_DIR / "peers.parquet"
STUB_CARDS_DIR = STUB_DIR / "cards"

# Logs
LOGS_DIR = ROOT / "logs"
DATA_LOGS_DIR = DATA_WORK / "logs"

CLAUDE_USAGE_CSV = LOGS_DIR / "claude_usage.csv"
USAGE_LOG = CLAUDE_USAGE_CSV  # Alias voor D
CLAUDE_CHECKPOINT_JSONL = DATA_LOGS_DIR / "claude_labels_checkpoint.jsonl"
