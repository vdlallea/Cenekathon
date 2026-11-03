"""Slice C: multilingual-e5-base embeddings per vacature (op de GPU).

Leest een tabel volgens het spine-contract (SPEC.md), maakt per vacature één
vector van titel + eerste ~400 woorden van de tekst, en schrijft:

    <out-dir>/embeddings*.npy          float32, (n, 768), L2-genormaliseerd
    <out-dir>/embeddings*_ids.parquet  kolom vacancy_id, rij i hoort bij matrixrij i

Bestandsnamen: bij --input spine.parquet krijg je de contractnamen
(embeddings.npy, embeddings_ids.parquet). Bij een andere input, bv.
sample_20k.parquet, komt de naam van de input erachter
(embeddings_sample_20k.npy), zodat de sample-run de volledige run nooit overschrijft.

Gebruik (op de server, in tmux, na nvidia-smi te hebben gecheckt):
    python peers/embed.py --limit 200          # rooktest
    python peers/embed.py                      # sample_20k.parquet
    python peers/embed.py --input ~/data/work/spine.parquet   # alles
"""
import argparse
import os
import re
import sys
import time
from pathlib import Path

import numpy as np
import pandas as pd

# TODO: vervangen door common/paths.py zodra D dat pusht.
WORK_DIR = Path.home() / "data" / "work"

MODEL_NAME = "intfloat/multilingual-e5-base"
MAX_WORDS = 400  # SPEC: titel + eerste ~400 woorden
MAX_TOKENS = 512  # limiet van e5; NL/FR-tekst haalt 400 woorden soms niet binnen 512 tokens
DIM = 768


def mask_company(df: pd.DataFrame, docs: pd.Series) -> pd.Series:
    """Haal de eigen bedrijfsnaam uit de tekst, zodat concurrenten niet op naam
    gelijken (juryvraag: kan het model een proxy gebruiken?). Per unieke naam,
    niet per rij: 1,5M rijen met één regex per rij zou veel te traag zijn."""
    if "company_raw" not in df.columns:
        return docs
    docs = docs.copy()
    for name, idx in df.groupby("company_raw", sort=False).groups.items():
        name = str(name).strip()
        if len(name) < 3:
            continue
        pattern = re.compile(re.escape(name), flags=re.IGNORECASE)
        docs.loc[idx] = docs.loc[idx].map(lambda t: pattern.sub(" ", t))
    return docs


def prepare_docs(df: pd.DataFrame, mask: bool = True) -> list[str]:
    """Eén string per vacature in e5-formaat ('passage: ...')."""
    title = df["title"].fillna("").astype(str).str.strip()
    body = df["text"].fillna("").astype(str).map(lambda t: " ".join(t.split()[:MAX_WORDS]))
    docs = title + "\n" + body
    if mask:
        docs = mask_company(df, docs)
    return ("passage: " + docs.str.strip()).tolist()


def embed(docs: list[str], batch_size: int, max_tokens: int = MAX_TOKENS) -> tuple[np.ndarray, float]:
    """Geeft (vectoren, seconden voor alleen het coderen). Laden en downloaden van het
    model en de eerste, trage batch (CUDA-opwarming) tellen niet mee in de tijd."""
    import torch
    from sentence_transformers import SentenceTransformer

    model = SentenceTransformer(MODEL_NAME, device="cuda")
    model.max_seq_length = max_tokens
    model.half()  # fp16: ruim sneller, kwaliteit voor cosine-similariteit gelijkwaardig
    model.encode(docs[:batch_size], batch_size=batch_size, show_progress_bar=False)  # opwarmen

    t0 = time.time()
    vecs = model.encode(
        docs,
        batch_size=batch_size,
        normalize_embeddings=True,  # cosine = inwendig product
        convert_to_numpy=True,
        show_progress_bar=True,
    )
    secs = time.time() - t0
    print(f"piek GPU-geheugen: {torch.cuda.max_memory_allocated() / 1e9:.1f} GB (grens in SPEC: 20 GB)")
    return vecs.astype(np.float32), secs


def output_names(input_path: Path) -> tuple[str, str]:
    if input_path.stem == "spine":
        return "embeddings.npy", "embeddings_ids.parquet"
    return f"embeddings_{input_path.stem}.npy", f"embeddings_{input_path.stem}_ids.parquet"


def write_atomic(out_dir: Path, npy_name: str, ids_name: str, vecs: np.ndarray, ids: pd.Series) -> None:
    """Eerst naar .tmp, dan hernoemen: anderen lezen deze bestanden mee."""
    out_dir.mkdir(parents=True, exist_ok=True)
    tmp_npy, tmp_ids = out_dir / (npy_name + ".tmp"), out_dir / (ids_name + ".tmp")
    with open(tmp_npy, "wb") as f:
        np.save(f, vecs)
    pd.DataFrame({"vacancy_id": ids.astype(str).to_numpy()}).to_parquet(tmp_ids, index=False)
    os.replace(tmp_npy, out_dir / npy_name)
    os.replace(tmp_ids, out_dir / ids_name)


def check(vecs: np.ndarray, n_expected: int) -> None:
    assert vecs.shape == (n_expected, DIM), vecs.shape
    assert vecs.dtype == np.float32
    assert np.isfinite(vecs).all(), "NaN of inf in embeddings"
    norms = np.linalg.norm(vecs, axis=1)
    assert np.allclose(norms, 1.0, atol=1e-2), f"normen buiten [0.99, 1.01]: {norms.min():.3f}..{norms.max():.3f}"


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--input", type=Path, default=WORK_DIR / "sample_20k.parquet")
    ap.add_argument("--out-dir", type=Path, default=WORK_DIR)
    ap.add_argument("--limit", type=int, default=None, help="alleen de eerste N rijen (rooktest)")
    ap.add_argument("--batch-size", type=int, default=128)
    ap.add_argument("--max-tokens", type=int, default=MAX_TOKENS,
                    help="kap elke vacature af op N tokens; 256 is ruwweg 2x sneller dan 512")
    ap.add_argument("--no-mask", action="store_true", help="bedrijfsnaam NIET uit de tekst halen")
    args = ap.parse_args()

    df = pd.read_parquet(args.input)
    missing = {"vacancy_id", "title", "text"} - set(df.columns)
    if missing:
        sys.exit(f"kolommen ontbreken in {args.input}: {sorted(missing)}")
    if args.limit:
        df = df.head(args.limit)
    if df["vacancy_id"].duplicated().any():
        sys.exit("vacancy_id is niet uniek: ontdubbelen is het werk van A (spine)")

    import torch

    if not torch.cuda.is_available():
        sys.exit("geen GPU gevonden: stop. Op CPU duurt dit uren en is het niet de bedoeling.")

    docs = prepare_docs(df, mask=not args.no_mask)
    print(f"{len(docs):,} vacatures | voorbeeld:\n{docs[0][:300]!r}\n")

    vecs, secs = embed(docs, args.batch_size, args.max_tokens)
    rate = len(docs) / secs
    print(f"{rate:.0f} docs/s (alleen coderen, {args.max_tokens} tokens) -> alle 1,5M vacatures ≈ "
          f"{1_542_169 / rate / 3600:.1f} uur. Met < 1.000 vacatures is dit een grove schatting.")

    check(vecs, len(df))
    npy_name, ids_name = output_names(args.input)
    write_atomic(args.out_dir, npy_name, ids_name, vecs, df["vacancy_id"])
    print(f"geschreven: {args.out_dir / npy_name} en {args.out_dir / ids_name}")


if __name__ == "__main__":
    main()
