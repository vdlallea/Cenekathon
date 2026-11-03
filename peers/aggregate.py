"""Slice C: aandelen per bedrijf en kwartaal + top-5 talentconcurrenten.

Leest, alles gekoppeld op vacancy_id (nooit op rijvolgorde):
    spine       (A)  vacancy_id, company_id, is_agency, quarter
    tags        (B)  vacancy_id, has_ai, ai_type (builder | user | governor | none)
    embeddings  (C)  embeddings*.npy + embeddings*_ids.parquet (zie embed.py)

Schrijft, volgens het contract in SPEC.md:
    company_quarter.parquet  company_id, quarter, n_postings, share_ai,
                             share_builder, share_user, share_governor, coverage_flag
    peers.parquet            company_id, peer_id, similarity, rank (1..5)

Tussenpersonen (is_agency) vallen uit beide tabellen. Een talentconcurrent is het
bedrijf waarvan de gemiddelde vacaturevector het dichtst bij die van de bank ligt
(cosine), alleen bedrijven met >= --min-postings vacatures.

Gebruik, op de volledige data:
    python peers/aggregate.py
Op de sample (veel minder vacatures per bedrijf, dus lagere drempel):
    python peers/aggregate.py --spine ~/data/work/sample_20k.parquet \\
        --embeddings ~/data/work/embeddings_sample_20k.npy --min-postings 20

LET OP: de uitvoer gaat standaard naar data/final/, de map met de echte eindtabellen.
Gebruik --out-dir voor proefruns (bijvoorbeeld op de sample).
"""
import argparse
import os
import sys
from pathlib import Path

import numpy as np
import pandas as pd

# TODO: vervangen door common/paths.py zodra D dat pusht.
WORK_DIR = Path.home() / "data" / "work"
FINAL_DIR = Path(__file__).resolve().parents[1] / "data" / "final"

COVERAGE_GAP = {"2026Q1", "2026Q2"}  # gat in de dataverzameling (zie SPEC.md)
TYPES = ("builder", "user", "governor")
CQ_COLUMNS = [
    "company_id", "quarter", "n_postings",
    "share_ai", "share_builder", "share_user", "share_governor", "coverage_flag",
]
PEER_COLUMNS = ["company_id", "peer_id", "similarity", "rank"]


def join_inputs(spine: pd.DataFrame, tags: pd.DataFrame | None, emb_ids: pd.Series,
                allow_partial: bool = False) -> pd.DataFrame:
    """Spine + tags + rijnummer in de embeddingmatrix, allemaal via vacancy_id.
    Met tags=None (peers-only) krijgt elke vacature een neutrale tag; de concurrentenlijst gebruikt die niet."""
    if not emb_ids.is_unique:
        sys.exit("embeddings_ids bevat dubbele vacancy_id's")
    cols = ["vacancy_id", "company_id", "is_agency", "quarter"]
    if tags is None:
        df = spine[cols].copy()
        df["has_ai"], df["ai_type"] = False, "none"
    else:
        df = spine[cols].merge(
            tags[["vacancy_id", "has_ai", "ai_type"]], on="vacancy_id", how="left", validate="one_to_one",
        )
    row_of = pd.Series(np.arange(len(emb_ids)), index=pd.Index(emb_ids.astype(str)))
    df["emb_row"] = df["vacancy_id"].astype(str).map(row_of)

    no_tag, no_emb = int(df["ai_type"].isna().sum()), int(df["emb_row"].isna().sum())
    if (no_tag or no_emb) and not allow_partial:
        sys.exit(f"{len(df):,} vacatures in de spine, maar {no_tag:,} zonder tag en {no_emb:,} zonder embedding. "
                 "Zo zouden de aandelen scheef staan. Draai B/C eerst op alles, of gebruik --allow-partial.")
    if no_tag or no_emb:
        print(f"WAARSCHUWING: {len(df) - len(df.dropna(subset=['ai_type', 'emb_row'])):,} van {len(df):,} "
              f"vacatures vallen weg (zonder tag: {no_tag:,}, zonder embedding: {no_emb:,})")
    df = df.dropna(subset=["ai_type", "emb_row"]).copy()
    df["emb_row"] = df["emb_row"].astype(np.int64)
    df["is_agency"] = df["is_agency"].astype(bool)
    df["has_ai"] = df["has_ai"].astype(bool)

    clash = int((df["has_ai"] != (df["ai_type"] != "none")).sum())
    if clash:
        print(f"WAARSCHUWING: {clash:,} vacatures waar has_ai en ai_type elkaar tegenspreken (B nakijken)")
    return df


def make_company_quarter(df: pd.DataFrame) -> pd.DataFrame:
    d = df[~df["is_agency"]]
    d = d.assign(
        share_ai=d["has_ai"].astype(float),
        **{f"share_{t}": (d["ai_type"] == t).astype(float) for t in TYPES},
    )
    out = (
        d.groupby(["company_id", "quarter"], sort=True)
        .agg(n_postings=("vacancy_id", "size"), share_ai=("share_ai", "mean"),
             share_builder=("share_builder", "mean"), share_user=("share_user", "mean"),
             share_governor=("share_governor", "mean"))
        .reset_index()
    )
    out["coverage_flag"] = out["quarter"].isin(COVERAGE_GAP)
    return out[CQ_COLUMNS].astype({
        "company_id": "string", "quarter": "string", "n_postings": "int64",
        "share_ai": "float64", "share_builder": "float64", "share_user": "float64",
        "share_governor": "float64", "coverage_flag": "bool",
    })


def company_vectors(df: pd.DataFrame, emb: np.ndarray, min_postings: int,
                    center: bool = False) -> tuple[list[str], np.ndarray]:
    """Gemiddelde vacaturevector per bedrijf (L2-genormaliseerd), zonder tussenpersonen.

    center=True haalt eerst het gemiddelde van alle bedrijfsvectoren eraf. e5-vectoren van gewone tekst
    liggen allemaal dicht bij elkaar (cosine 0,99+ voor bijna elk bedrijf); het gemeenschappelijke deel
    (taal, vacature-opmaak) domineert dan de score. Dat eraf halen laat zien waarin bedrijven verschillen."""
    d = df[~df["is_agency"]]
    counts = d.groupby("company_id").size()
    d = d[d["company_id"].isin(counts[counts >= min_postings].index)]
    rows = d["emb_row"].to_numpy()
    names, vecs = [], []
    for cid, idx in d.groupby("company_id", sort=True).indices.items():
        v = emb[np.sort(rows[idx])].mean(axis=0, dtype=np.float64)
        names.append(str(cid))
        vecs.append(v / np.linalg.norm(v))
    if not vecs:
        return [], np.zeros((0, emb.shape[1]), dtype=np.float32)
    mat = np.vstack(vecs)
    if center and len(names) > 2:
        mat = mat - mat.mean(axis=0, keepdims=True)
        norms = np.linalg.norm(mat, axis=1, keepdims=True)
        mat = mat / np.where(norms > 0, norms, 1.0)
    return names, mat.astype(np.float32)


def top_peers(names: list[str], vecs: np.ndarray, k: int = 5, block: int = 1024) -> pd.DataFrame:
    """Top-k dichtstbijzijnde bedrijven per bedrijf, per blok: geheugen blijft block x m."""
    m = len(names)
    kk = min(k, m - 1)
    rows = []
    for start in range(0, m, block):
        sims = vecs[start:start + block] @ vecs.T
        sims[np.arange(sims.shape[0]), np.arange(start, start + sims.shape[0])] = -np.inf  # niet zichzelf
        if kk < 1:
            break
        top = np.argpartition(-sims, kk - 1, axis=1)[:, :kk]
        for i in range(sims.shape[0]):
            order = top[i][np.argsort(-sims[i, top[i]])]
            for rank, j in enumerate(order, start=1):
                rows.append((names[start + i], names[j], float(sims[i, j]), rank))
    return pd.DataFrame(rows, columns=PEER_COLUMNS).astype({
        "company_id": "string", "peer_id": "string", "similarity": "float64", "rank": "int64",
    })


def validate(cq: pd.DataFrame | None, peers: pd.DataFrame) -> None:
    assert list(peers.columns) == PEER_COLUMNS
    assert not peers.duplicated(["company_id", "rank"]).any()
    assert (peers["company_id"] != peers["peer_id"]).all()
    assert peers["rank"].between(1, 5).all()
    if cq is None:  # peers-only: geen company_quarter om tegen te controleren
        return
    assert list(cq.columns) == CQ_COLUMNS
    assert not cq.duplicated(["company_id", "quarter"]).any()
    shares = cq[["share_ai", "share_builder", "share_user", "share_governor"]]
    assert ((shares >= 0) & (shares <= 1)).all().all()
    assert set(peers["company_id"]) <= set(cq["company_id"]), "peers voor een bedrijf zonder aandelen"


def write_atomic(df: pd.DataFrame, path: Path) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_name(path.name + ".tmp")
    df.to_parquet(tmp, index=False)
    os.replace(tmp, path)


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--spine", type=Path, default=WORK_DIR / "spine.parquet")
    ap.add_argument("--tags", type=Path, default=WORK_DIR / "tags.parquet")
    ap.add_argument("--embeddings", type=Path, default=WORK_DIR / "embeddings.npy")
    ap.add_argument("--out-dir", type=Path, default=FINAL_DIR)
    ap.add_argument("--min-postings", type=int, default=200)
    ap.add_argument("--center", action="store_true",
                    help="haal het gemiddelde van alle bedrijfsvectoren eraf voor het vergelijken (spreidt de scores uit)")
    ap.add_argument("--top-k", type=int, default=5)
    ap.add_argument("--allow-partial", action="store_true", help="ga door als tags of embeddings voor sommige vacatures ontbreken")
    ap.add_argument("--peers-only", action="store_true",
                    help="alleen peers.parquet, zonder tags en company_quarter (de concurrentenlijst heeft B's tags niet nodig)")
    args = ap.parse_args()

    ids_path = args.embeddings.with_name(args.embeddings.stem + "_ids.parquet")
    spine = pd.read_parquet(args.spine)
    tags = None if args.peers_only else pd.read_parquet(args.tags)
    emb_ids = pd.read_parquet(ids_path)["vacancy_id"]
    emb = np.load(args.embeddings, mmap_mode="r")
    if len(emb) != len(emb_ids):
        sys.exit(f"{args.embeddings.name} heeft {len(emb):,} rijen, maar {ids_path.name} heeft {len(emb_ids):,} ids")

    df = join_inputs(spine, tags, emb_ids, allow_partial=args.allow_partial)
    n_agency = int(df["is_agency"].sum())
    print(f"{len(df):,} vacatures gebruikt, waarvan {n_agency:,} van tussenpersonen ({n_agency / len(df):.1%}) die wegvallen")

    cq = None if args.peers_only else make_company_quarter(df)
    names, vecs = company_vectors(df, emb, args.min_postings, center=args.center)
    peers = top_peers(names, vecs, k=args.top_k)
    validate(cq, peers)
    if cq is not None:
        print(f"{cq['company_id'].nunique():,} bedrijven in company_quarter, {len(names):,} met >= {args.min_postings} "
              f"vacatures in peers")
        write_atomic(cq, args.out_dir / "company_quarter.parquet")
    else:
        print(f"peers-only: {len(names):,} bedrijven met >= {args.min_postings} vacatures; company_quarter niet aangemaakt")
    write_atomic(peers, args.out_dir / "peers.parquet")
    print(f"geschreven naar {args.out_dir}\n\nControle met het oog: top-5 voor de grootste bedrijven")
    for cid in df[~df["is_agency"]]["company_id"].value_counts().head(5).index:
        p = peers[peers["company_id"] == cid]
        print(f"  {cid}: " + ", ".join(f"{r.peer_id} ({r.similarity:.3f})" for r in p.itertuples()) if len(p) else f"  {cid}: (onder de drempel)")


if __name__ == "__main__":
    main()
