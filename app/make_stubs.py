"""Maakt nepdata (stubs) volgens het contract in SPEC.md.

Schrijft alleen naar app/stubs/. Getallen zijn verzonnen; alle bestanden zijn gemarkeerd als stub.
Draaien: python app/make_stubs.py
"""

import json
import sys
from pathlib import Path

import pandas as pd

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from common import paths  # noqa: E402

COMPANIES = ["kbc", "ing", "abn-amro", "rabobank", "belfius", "bnp-paribas-fortis"]
QUARTERS = [f"{y}Q{q}" for y in (2023, 2024, 2025) for q in (1, 2, 3, 4)] + ["2026Q1", "2026Q2", "2026Q3"]
GAP_QUARTERS = {"2026Q1", "2026Q2"}  # gat in de dataverzameling (SPEC: Definities)


def make_company_quarter() -> pd.DataFrame:
    rows = []
    for i, company in enumerate(COMPANIES):
        for j, quarter in enumerate(QUARTERS):
            n = 120 + 15 * i + 4 * j
            share_ai = round(0.03 + 0.002 * j + 0.004 * i, 4)
            builder, user, governor = 0.35, 0.45, 0.20
            rows.append({
                "company_id": company,
                "quarter": quarter,
                "n_postings": n,
                "share_ai": share_ai,
                "share_builder": round(share_ai * builder, 4),
                "share_user": round(share_ai * user, 4),
                "share_governor": round(share_ai * governor, 4),
                "coverage_flag": quarter in GAP_QUARTERS,
                "is_stub": True,
            })
    return pd.DataFrame(rows)


def make_peers() -> pd.DataFrame:
    rows = []
    for company in COMPANIES:
        others = [c for c in COMPANIES if c != company]
        for rank, peer in enumerate(others[:5], start=1):
            rows.append({
                "company_id": company,
                "peer_id": peer,
                "similarity": round(0.95 - 0.04 * rank, 3),
                "rank": rank,
                "is_stub": True,
            })
    return pd.DataFrame(rows)


def make_kbc_card() -> dict:
    return {
        "company_id": "kbc",
        "headline": "KBC werft minder AI-bewakers aan dan haar concurrenten (STUB, verzonnen cijfers)",
        "actions": [
            {"advice": "Werf 5 AI-governanceprofielen aan", "cost_eur": 450000},
            {"advice": "Schoolt 15 risk-analisten om", "cost_eur": 120000},
        ],
        "evidence": {"share_ai": 0.06, "peer_share_ai": 0.11, "n": 1840},
        "stub": True,
    }


def main() -> None:
    paths.STUB_DIR.mkdir(parents=True, exist_ok=True)
    paths.STUB_CARDS_DIR.mkdir(parents=True, exist_ok=True)

    make_company_quarter().to_parquet(paths.STUB_COMPANY_QUARTER, index=False)
    make_peers().to_parquet(paths.STUB_PEERS, index=False)
    with open(paths.STUB_CARDS_DIR / "kbc.json", "w", encoding="utf-8") as f:
        json.dump(make_kbc_card(), f, ensure_ascii=False, indent=2)
    print("Stubs geschreven naar", paths.STUB_DIR)


if __name__ == "__main__":
    main()
