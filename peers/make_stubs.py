"""Slice C: stubs voor company_quarter.parquet en peers.parquet.

Nepwaarden, juiste kolommen en types volgens het contract in SPEC.md.
Doel: D kan de Streamlit-app bouwen zonder op echte cijfers te wachten.
LET OP: schrijf dit nooit naar data/final/. Daar horen alleen de echte tabellen; de app van D
toont een banner als die ontbreken, en ziet nepdata anders aan voor het echte resultaat.

Gebruik (vanuit de repo-root), bijvoorbeeld:
    python peers/make_stubs.py --out-dir /tmp/stubs_c
"""
import argparse
from pathlib import Path

import numpy as np
import pandas as pd


SEED = 42
COMPANIES = ["ing", "abn-amro", "rabobank", "kbc", "belfius", "bnp-paribas-fortis"]
QUARTERS = [f"{y}Q{q}" for y in (2024, 2025, 2026) for q in (1, 2, 3, 4)][:-1]  # t/m 2026Q3
COVERAGE_GAP = {"2026Q1", "2026Q2"}  # gat in de dataverzameling (zie SPEC.md)

CQ_COLUMNS = [
    "company_id", "quarter", "n_postings",
    "share_ai", "share_builder", "share_user", "share_governor", "coverage_flag",
]
PEER_COLUMNS = ["company_id", "peer_id", "similarity", "rank"]


def make_company_quarter(rng: np.random.Generator) -> pd.DataFrame:
    rows = []
    for company in COMPANIES:
        base = rng.uniform(0.02, 0.06)  # startniveau AI-aandeel
        for i, quarter in enumerate(QUARTERS):
            total = base + 0.006 * i  # lichte stijging over tijd
            # één label per vacature -> de drie types tellen op tot share_ai
            mix = rng.dirichlet([3.0, 5.0, 1.5])
            builder, user, governor = (total * mix).round(4)
            rows.append({
                "company_id": company,
                "quarter": quarter,
                "n_postings": int(rng.integers(150, 600)),
                "share_ai": round(float(builder + user + governor), 4),
                "share_builder": float(builder),
                "share_user": float(user),
                "share_governor": float(governor),
                "coverage_flag": quarter in COVERAGE_GAP,
            })
    return pd.DataFrame(rows, columns=CQ_COLUMNS).astype({
        "company_id": "string", "quarter": "string", "n_postings": "int64",
        "share_ai": "float64", "share_builder": "float64",
        "share_user": "float64", "share_governor": "float64",
        "coverage_flag": "bool",
    })


def make_peers(rng: np.random.Generator) -> pd.DataFrame:
    rows = []
    for company in COMPANIES:
        others = [c for c in COMPANIES if c != company]  # 5 anderen = top-5
        sims = np.sort(rng.uniform(0.80, 0.97, size=len(others)))[::-1].round(4)
        order = rng.permutation(len(others))
        for rank, (idx, sim) in enumerate(zip(order, sims), start=1):
            rows.append({
                "company_id": company, "peer_id": others[idx],
                "similarity": float(sim), "rank": rank,
            })
    return pd.DataFrame(rows, columns=PEER_COLUMNS).astype({
        "company_id": "string", "peer_id": "string",
        "similarity": "float64", "rank": "int64",
    })


def validate(cq: pd.DataFrame, peers: pd.DataFrame) -> None:
    assert list(cq.columns) == CQ_COLUMNS, cq.columns
    assert list(peers.columns) == PEER_COLUMNS, peers.columns
    assert not cq.duplicated(["company_id", "quarter"]).any()
    assert not peers.duplicated(["company_id", "rank"]).any()
    shares = cq[["share_ai", "share_builder", "share_user", "share_governor"]]
    assert ((shares >= 0) & (shares <= 1)).all().all()
    gap = (cq["share_builder"] + cq["share_user"] + cq["share_governor"] - cq["share_ai"]).abs()
    assert (gap < 1e-3).all(), "types moeten optellen tot share_ai"
    assert peers["rank"].between(1, 5).all()
    assert (peers["company_id"] != peers["peer_id"]).all()
    assert (peers.groupby("company_id")["similarity"]
            .apply(lambda s: s.is_monotonic_decreasing)).all(), "similarity moet dalen met rank"


def main() -> None:
    ap = argparse.ArgumentParser(description="Nepdata voor company_quarter en peers")
    ap.add_argument("--out-dir", type=Path, required=True, help="map voor de stubs (niet data/final)")
    out_dir = ap.parse_args().out_dir
    if out_dir.resolve() == (Path(__file__).resolve().parents[1] / "data" / "final"):
        raise SystemExit("data/final is voor de echte tabellen; kies een andere map")
    rng = np.random.default_rng(SEED)
    cq = make_company_quarter(rng)
    peers = make_peers(rng)
    validate(cq, peers)

    out_dir.mkdir(parents=True, exist_ok=True)
    cq.to_parquet(out_dir / "company_quarter.parquet", index=False)
    peers.to_parquet(out_dir / "peers.parquet", index=False)
    print(f"company_quarter.parquet: {len(cq)} rijen | peers.parquet: {len(peers)} rijen -> {out_dir}")


if __name__ == "__main__":
    main()
