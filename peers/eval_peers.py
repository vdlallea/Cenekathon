"""Slice C: evaluatie van de concurrentenlijst (peers.parquet).

Antwoord op de juryvraag "Hoe weten jullie dat de concurrentenlijst klopt?", in getallen:
 1. Bekende concurrenten: staan ze in elkaars top-k, en hoeveel beter is dat dan toeval?
 2. Per land: hoeveel peers zitten in hetzelfde land (alleen met --companies), tegenover toeval?
 3. De top-k van elke bekende bank, om met het oog na te kijken.

Gebruik (vanuit de repo-root):
    python peers/eval_peers.py                       # leest data/final/peers.parquet
    python peers/eval_peers.py --peers ~/data/work/c_test/peers.parquet \\
        --companies ~/data/work/companies.parquet
"""
import argparse
from pathlib import Path

import pandas as pd

# TODO: vervangen door common/paths.py (PEERS) zodra dat nuttig is.
FINAL_DIR = Path(__file__).resolve().parents[1] / "data" / "final"

# Bedrijf-id's zoals in A's aliaslijst (spine/process.py, CANONICAL). Uitbreiden na de top-50-handcheck.
KNOWN_GROUPS = {
    "NL grootbanken": ["ing", "abn-amro", "rabobank"],
    "BE banken": ["kbc", "belfius", "bnp-paribas-fortis"],
    "UK retailbanken": ["barclays", "lloyds", "natwest", "hsbc", "santander", "nationwide"],
}


def known_competitors(peers: pd.DataFrame, groups: dict[str, list[str]] = KNOWN_GROUPS):
    """Per bekende bank: hoeveel van haar groepsgenoten staan in haar top-k?

    Geeft (tabel, ontbrekende bedrijven, toevalsbasislijn). Toeval: k willekeurige bedrijven
    uit het universum kiezen vindt gemiddeld k / (N - 1) van de groepsgenoten."""
    universe = set(peers["company_id"])
    k = int(peers["rank"].max())
    baseline = k / (len(universe) - 1) if len(universe) > 1 else float("nan")
    rows, missing = [], []
    for group, members in groups.items():
        present = [m for m in members if m in universe]
        missing += [m for m in members if m not in universe]
        for cid in present:
            mates = set(present) - {cid}
            if not mates:
                continue
            top = peers[peers["company_id"] == cid].sort_values("rank")
            ranks = top.loc[top["peer_id"].isin(mates), "rank"].tolist()
            rows.append({"groep": group, "bedrijf": cid, "genoten": len(mates), "gevonden": len(ranks),
                         "recall": len(ranks) / len(mates), "ranks": ranks})
    return pd.DataFrame(rows), sorted(set(missing)), baseline


def country_overlap(peers: pd.DataFrame, companies: pd.DataFrame) -> tuple[float, float]:
    """Aandeel peers in hetzelfde hoofdland, en wat toeval zou geven."""
    c = companies[["company_id", "main_country"]]
    m = peers.merge(c, on="company_id").merge(
        c.rename(columns={"company_id": "peer_id", "main_country": "peer_country"}), on="peer_id")
    observed = float((m["main_country"] == m["peer_country"]).mean())
    uni = c[c["company_id"].isin(set(peers["company_id"]))]
    n, by_country = len(uni), uni["main_country"].value_counts()
    baseline = float((by_country * (by_country - 1)).sum() / (n * (n - 1))) if n > 1 else float("nan")
    return observed, baseline


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--peers", type=Path, default=FINAL_DIR / "peers.parquet")
    ap.add_argument("--companies", type=Path, default=None, help="companies.parquet van A, voor de landencheck")
    args = ap.parse_args()

    peers = pd.read_parquet(args.peers)
    n = peers["company_id"].nunique()
    print(f"{len(peers):,} rijen, {n:,} bedrijven, top-{int(peers['rank'].max())}\n")

    table, missing, baseline = known_competitors(peers)
    print("1. Bekende concurrenten in elkaars top-k")
    if table.empty:
        print("   Geen enkele bekende groep heeft minstens twee bedrijven in peers.parquet.")
    else:
        print(table.drop(columns="recall").to_string(index=False))
        recall = float(table["recall"].mean())
        print(f"\n   Gemiddeld gevonden: {recall:.0%} van de groepsgenoten. Toeval: {baseline:.1%}"
              f" (dus {recall / baseline:.1f}x beter dan toeval, n = {len(table)} banken, {n:,} bedrijven in het universum)")
        for cid in table["bedrijf"]:
            top = peers[peers["company_id"] == cid].sort_values("rank")
            print(f"   {cid}: " + ", ".join(f"{r.peer_id} ({r.similarity:.2f})" for r in top.itertuples()))
    if missing:
        print(f"\n   Ontbreken in peers.parquet (onder de drempel, tussenpersoon of andere company_id): {', '.join(missing)}")

    if args.companies:
        obs, base = country_overlap(peers, pd.read_parquet(args.companies))
        print(f"\n2. Peers in hetzelfde land: {obs:.0%} (toeval: {base:.0%})")


if __name__ == "__main__":
    main()
