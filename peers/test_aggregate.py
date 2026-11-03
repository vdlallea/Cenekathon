"""Zelftest voor peers/aggregate.py op synthetische data. Geen GPU nodig.

    python peers/test_aggregate.py
"""
import importlib.util
from pathlib import Path

import numpy as np
import pandas as pd

spec = importlib.util.spec_from_file_location("aggregate", Path(__file__).with_name("aggregate.py"))
agg = importlib.util.module_from_spec(spec)
spec.loader.exec_module(agg)

rng = np.random.default_rng(0)
DIM = 16
centers = {"A": rng.normal(size=DIM), "B": rng.normal(size=DIM)}
COMPANIES = {"a1": "A", "a2": "A", "a3": "A", "b1": "B", "b2": "B", "b3": "B", "tiny": "A", "hays": "A"}
N = {"tiny": 5, "hays": 300}  # tiny onder de drempel, hays is een tussenpersoon
QUARTERS = ["2025Q4", "2026Q1", "2026Q3"]

rows, vecs = [], []
for cid, cl in COMPANIES.items():
    for i in range(N.get(cid, 150)):
        v = centers[cl] + rng.normal(scale=0.3, size=DIM)
        ai = rng.random() < 0.25
        t = str(rng.choice(agg.TYPES)) if ai else "none"
        rows.append((f"{cid}-{i}", cid, cid == "hays", QUARTERS[i % 3], ai, t))
        vecs.append(v / np.linalg.norm(v))
spine = pd.DataFrame(rows, columns=["vacancy_id", "company_id", "is_agency", "quarter", "has_ai", "ai_type"])
emb = np.array(vecs, dtype=np.float32)

# Matrix in een andere volgorde dan de spine: koppelen moet via vacancy_id gaan, niet via rijvolgorde
perm = rng.permutation(len(spine))
emb_shuffled, emb_ids = emb[perm], spine["vacancy_id"].iloc[perm].reset_index(drop=True)
tags = spine[["vacancy_id", "has_ai", "ai_type"]].sample(frac=1, random_state=1)

df = agg.join_inputs(spine.drop(columns=["has_ai", "ai_type"]), tags, emb_ids)
assert len(df) == len(spine)

# company_quarter
cq = agg.make_company_quarter(df)
assert "hays" not in set(cq["company_id"]), "tussenpersoon mag niet in company_quarter"
assert list(cq.columns) == agg.CQ_COLUMNS
assert cq["coverage_flag"].eq(cq["quarter"].isin({"2026Q1", "2026Q2"})).all()
parts = cq[["share_builder", "share_user", "share_governor"]].sum(axis=1)
assert np.allclose(parts, cq["share_ai"]), "types moeten optellen tot share_ai"
a1 = cq[(cq.company_id == "a1") & (cq.quarter == "2025Q4")].iloc[0]
truth = spine[(spine.company_id == "a1") & (spine.quarter == "2025Q4")]
assert a1.n_postings == len(truth) and np.isclose(a1.share_ai, truth.has_ai.mean())

# peers: juiste bedrijven, juiste volgorde, uitgelijnd op id (niet op rij)
names, vecs_c = agg.company_vectors(df, emb_shuffled, min_postings=100)
assert set(names) == {"a1", "a2", "a3", "b1", "b2", "b3"}, names  # tiny en hays vallen weg
peers = agg.top_peers(names, vecs_c, k=5)
assert len(peers) == 6 * 5 and (peers.company_id != peers.peer_id).all()
for cid, cl in [("a1", "A"), ("b2", "B")]:
    p = peers[peers.company_id == cid].sort_values("rank")
    own = {c for c, k in COMPANIES.items() if k == cl and c in names} - {cid}
    assert set(p.peer_id.iloc[:2]) == own, (cid, p)
    assert p.similarity.is_monotonic_decreasing
agg.validate(cq, peers)

# blokgrootte mag de uitkomst niet veranderen (schaalbaarheid)
small = agg.top_peers(names, vecs_c, k=5, block=2)
pd.testing.assert_frame_equal(peers.reset_index(drop=True), small.reset_index(drop=True))

# ontbrekende tags: hard stoppen, tenzij --allow-partial
try:
    agg.join_inputs(spine.drop(columns=["has_ai", "ai_type"]), tags.iloc[:-10], emb_ids)
    raise SystemExit("had moeten stoppen bij ontbrekende tags")
except SystemExit as e:
    assert "zonder tag" in str(e), e
part = agg.join_inputs(spine.drop(columns=["has_ai", "ai_type"]), tags.iloc[:-10], emb_ids, allow_partial=True)
assert len(part) == len(spine) - 10

# peers-only: zonder tags moet dezelfde concurrentenlijst uitkomen
df_np = agg.join_inputs(spine.drop(columns=["has_ai", "ai_type"]), None, emb_ids)
names_np, vecs_np = agg.company_vectors(df_np, emb_shuffled, min_postings=100)
assert names_np == names
peers_np = agg.top_peers(names_np, vecs_np, k=5)
agg.validate(None, peers_np)
pd.testing.assert_frame_equal(peers_np.reset_index(drop=True), peers.reset_index(drop=True))

# evaluatie van de concurrentenlijst
spec_e = importlib.util.spec_from_file_location("eval_peers", Path(__file__).with_name("eval_peers.py"))
ev = importlib.util.module_from_spec(spec_e)
spec_e.loader.exec_module(ev)
peers2 = agg.top_peers(names, vecs_c, k=2)
table, missing, baseline = ev.known_competitors(
    peers2, {"A": ["a1", "a2", "a3"], "B": ["b1", "b2", "b3"], "X": ["zzz", "a1"]})
assert missing == ["zzz"], missing
assert np.isclose(baseline, 2 / 5), baseline
assert (table["recall"] == 1.0).all() and len(table) == 6, table
companies = pd.DataFrame({"company_id": names, "main_country": ["BE" if n.startswith("a") else "NL" for n in names]})
observed, base = ev.country_overlap(peers2, companies)
assert observed == 1.0 and np.isclose(base, 12 / 30), (observed, base)
print("peers-only en evaluatie ok")

print("alle controles geslaagd")
