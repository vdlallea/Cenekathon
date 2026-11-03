"""Alle paden van het project op één plek. Wijzig dit alleen via een PR die in de groep is aangekondigd (zie SPEC.md)."""

from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]

# Eindbestanden (klein, wel in git)
FINAL_DIR = ROOT / "data" / "final"
CARDS_DIR = FINAL_DIR / "cards"
COMPANY_QUARTER = FINAL_DIR / "company_quarter.parquet"
PEERS = FINAL_DIR / "peers.parquet"

# Stubs: nepdata voor als de echte bestanden nog niet bestaan
STUB_DIR = ROOT / "app" / "stubs"
STUB_COMPANY_QUARTER = STUB_DIR / "company_quarter.parquet"
STUB_PEERS = STUB_DIR / "peers.parquet"
STUB_CARDS_DIR = STUB_DIR / "cards"

# Logs (niet in git)
LOGS_DIR = ROOT / "logs"
USAGE_LOG = LOGS_DIR / "claude_usage.csv"
