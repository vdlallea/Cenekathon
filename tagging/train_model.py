"""Logistische regressie voor AI-tagging (slice B).

Wat dit script doet:
1. Wacht (optioneel) op C's embeddings.npy + embeddings_ids.parquet.
2. Koppelt elke embedding aan zijn vacancy_id via embeddings_ids (rij i hoort bij rij i).
   Nooit op spine-volgorde vertrouwen.
3. Traint een scikit-learn LogisticRegression op de Claude-labels (claude_labels_1500,
   alleen parse_ok). Gewichten = 1 / inclusion_prob uit label_sample_1500 (correctie voor
   de oversampling van hits en BE/NL), genormaliseerd naar gemiddelde 1.
4. Evalueert op de testset (claude_test_300, nooit in training gebruikt):
   - AI ja/nee: precision, recall, F1 (model en keyword-basislijn ter vergelijking)
   - F1 per ai_type (builder, user, governor, none)
   - AI ja/nee uitgesplitst per taal
5. Schrijft tags.parquet (contract) met source="model" voor alle vacatures met een embedding.
   Een bestaand tags.parquet wordt eerst gekopieerd naar een back-up met tijdstempel.

Draaien (op de server):
  ~/venv/bin/python train_model.py                 # wacht niet, faalt als embeddings ontbreken
  ~/venv/bin/python train_model.py --wait-minutes 600
"""

from __future__ import annotations

import argparse
import shutil
import sys
import time
from datetime import datetime
from pathlib import Path

import numpy as np
import pandas as pd
from sklearn.linear_model import LogisticRegression
from sklearn.metrics import classification_report, precision_recall_fscore_support

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from common.paths import (  # noqa: E402
    CLAUDE_LABELS_PARQUET,
    DATA_WORK,
    LABEL_SAMPLE_PARQUET,
    TAGS_PARQUET,
    TEST_SET_PARQUET,
)

SEED = 42
TYPES = ["builder", "user", "governor", "none"]
CLAUDE_TEST_PARQUET = DATA_WORK / "claude_test_300.parquet"
EMBEDDINGS_NPY = DATA_WORK / "embeddings.npy"
EMBEDDINGS_IDS = DATA_WORK / "embeddings_ids.parquet"


# --- Laden --------------------------------------------------------------------
def wait_for_embeddings(npy: Path, ids: Path, minutes: float) -> None:
    """Wacht tot beide embeddingbestanden bestaan (C levert ze op). Faalt na de wachttijd."""
    deadline = time.time() + minutes * 60
    announced = False
    while not (npy.exists() and ids.exists()):
        if time.time() >= deadline:
            missing = [str(p) for p in (npy, ids) if not p.exists()]
            raise SystemExit(f"Embeddings ontbreken nog: {missing}. Wacht op C en draai opnieuw.")
        if not announced:
            print(f"Wachten op embeddings van C: {npy.name}, {ids.name} ...", flush=True)
            announced = True
        time.sleep(60)


def load_embeddings(npy: Path, ids_path: Path) -> tuple[np.ndarray, dict[str, int]]:
    vecs = np.load(npy)
    ids = pd.read_parquet(ids_path)["vacancy_id"].astype(str).to_numpy()
    if vecs.ndim != 2 or vecs.shape[0] != len(ids):
        raise SystemExit(
            f"Mismatch: {npy.name} heeft {vecs.shape} maar {ids_path.name} heeft {len(ids)} ID's."
        )
    if len(set(ids)) != len(ids):
        raise SystemExit(f"{ids_path.name} bevat dubbele vacancy_id's.")
    index = {vid: i for i, vid in enumerate(ids)}
    print(f"Embeddings: {vecs.shape[0]} vectoren van {vecs.shape[1]} dimensies.")
    return vecs.astype(np.float32), index


def load_labeled(path: Path, name: str) -> pd.DataFrame:
    df = pd.read_parquet(path)
    df["vacancy_id"] = df["vacancy_id"].astype(str)
    ok = df[df["parse_ok"].astype(bool)].copy()
    print(f"{name}: {len(ok)} van {len(df)} rijen met een geldig Claude-label.")
    return ok


# --- Modelleren ----------------------------------------------------------------
def rows_with_embedding(df: pd.DataFrame, index: dict[str, int], name: str) -> pd.DataFrame:
    has = df["vacancy_id"].isin(index.keys())
    if (~has).any():
        print(f"WAARSCHUWING {name}: {int((~has).sum())} vacatures hebben geen embedding en worden overgeslagen.")
    return df[has].reset_index(drop=True)


def training_weights(train: pd.DataFrame, label_sample: Path) -> np.ndarray:
    """1/inclusion_prob uit label_sample (correctie voor oversampling), genormaliseerd naar gemiddelde 1."""
    if not label_sample.exists():
        print("WAARSCHUWING: label_sample_1500 ontbreekt; alle gewichten = 1.")
        return np.ones(len(train))
    ls = pd.read_parquet(label_sample, columns=["vacancy_id", "inclusion_prob"])
    ls["vacancy_id"] = ls["vacancy_id"].astype(str)
    merged = train[["vacancy_id"]].merge(ls, on="vacancy_id", how="left")
    prob = merged["inclusion_prob"].fillna(1.0).clip(lower=1e-6).to_numpy()
    w = 1.0 / prob
    return w / w.mean()


def _prf(y_true: np.ndarray, y_pred: np.ndarray) -> tuple[float, float, float]:
    p, r, f, _ = precision_recall_fscore_support(
        y_true, y_pred, average="binary", zero_division=0
    )
    return float(p), float(r), float(f)


def evaluate(test: pd.DataFrame, pred_type: np.ndarray, keyword_has_ai: np.ndarray) -> None:
    true_type = test["ai_type"].astype(str).to_numpy()
    true_has = true_type != "none"
    pred_has = pred_type != "none"

    print("\n=== Evaluatie op testset (Claude-labels) ===")
    print(f"Testvacatures: {len(test)}, waarvan AI volgens Claude: {int(true_has.sum())}")
    if true_has.sum() < 30:
        print("LET OP: weinig AI-positieven in de testset; precision/recall zijn ruw.")

    mp, mr, mf = _prf(true_has, pred_has)
    kp, kr, kf = _prf(true_has, keyword_has_ai)
    print("\nAI ja/nee:")
    print(f"  model:   precision={mp:.3f} recall={mr:.3f} F1={mf:.3f}")
    print(f"  keyword: precision={kp:.3f} recall={kr:.3f} F1={kf:.3f}  (basislijn)")

    print("\nClassification report per ai_type (model):")
    print(classification_report(true_type, pred_type, labels=TYPES, zero_division=0, digits=3))

    print("AI ja/nee per taal (model):")
    print(f"  {'taal':<8}{'n':>5}{'pos':>5}{'prec':>8}{'rec':>8}{'F1':>8}")
    for lang, sub in test.assign(_pred=pred_type, _true=true_type).groupby(
        test["lang"].fillna("unknown").astype(str), sort=True
    ):
        ti = sub["_true"].to_numpy() != "none"
        pi = sub["_pred"].to_numpy() != "none"
        p, r, f = _prf(ti, pi)
        print(f"  {lang:<8}{len(sub):>5}{int(ti.sum()):>5}{p:>8.3f}{r:>8.3f}{f:>8.3f}")


def build_tags(ids: list[str], vecs: np.ndarray, model: LogisticRegression) -> pd.DataFrame:
    proba = model.predict_proba(vecs)
    classes = list(model.classes_)
    pred_idx = proba.argmax(axis=1)
    pred = np.array(classes)[pred_idx]
    conf = proba.max(axis=1).astype("float64")
    return pd.DataFrame({
        "vacancy_id": pd.Series(ids, dtype="object").astype(str),
        "has_ai": pd.Series(pred != "none", dtype="bool"),
        "ai_type": pd.Series(pred, dtype="object").astype(str),
        "confidence": pd.Series(conf, dtype="float64"),
        # Let op: pd.Series("model") is een Series van lengte 1 en geeft NaN voor de rest.
        "source": pd.Series(["model"] * len(ids), dtype="object"),
    })


def write_tags(tags: pd.DataFrame, out: Path) -> None:
    out.parent.mkdir(parents=True, exist_ok=True)
    if out.exists():
        stamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        backup = out.with_name(f"{out.stem}_before_model_{stamp}{out.suffix}")
        shutil.copy2(out, backup)
        print(f"Bestaand tags.parquet gekopieerd naar {backup.name}")
    tags.to_parquet(out, index=False)
    print(f"Geschreven: {out} ({len(tags)} rijen)")


# --- Main ----------------------------------------------------------------------
def parse_args(argv=None) -> argparse.Namespace:
    p = argparse.ArgumentParser(description="Logistische regressie + tags.parquet (slice B).")
    p.add_argument("--train", type=Path, default=CLAUDE_LABELS_PARQUET)
    p.add_argument("--test", type=Path, default=CLAUDE_TEST_PARQUET)
    p.add_argument("--test-meta", type=Path, default=TEST_SET_PARQUET,
                   help="test_set_300 voor taal en keyword-basislijn")
    p.add_argument("--label-sample", type=Path, default=LABEL_SAMPLE_PARQUET)
    p.add_argument("--embeddings", type=Path, default=EMBEDDINGS_NPY)
    p.add_argument("--embedding-ids", type=Path, default=EMBEDDINGS_IDS)
    p.add_argument("--out", type=Path, default=TAGS_PARQUET)
    p.add_argument("--wait-minutes", type=float, default=0,
                   help="Hoelang wachten op de embeddings van C (0 = niet wachten)")
    p.add_argument("--C", type=float, default=1.0, help="Regularisatie (inverse)")
    p.add_argument("--no-write", action="store_true", help="Alleen evalueren, niet wegschrijven")
    return p.parse_args(argv)


def main(argv=None) -> None:
    args = parse_args(argv)
    if args.wait_minutes > 0:
        wait_for_embeddings(args.embeddings, args.embedding_ids, args.wait_minutes)
    if not (args.embeddings.exists() and args.embedding_ids.exists()):
        raise SystemExit(
            f"Embeddings ontbreken: {args.embeddings.name} / {args.embedding_ids.name}. "
            "Wacht op C (of gebruik --wait-minutes)."
        )

    vecs, index = load_embeddings(args.embeddings, args.embedding_ids)

    train = rows_with_embedding(load_labeled(args.train, "train"), index, "train")
    test = rows_with_embedding(load_labeled(args.test, "test"), index, "test")
    if set(train["vacancy_id"]) & set(test["vacancy_id"]):
        raise SystemExit("Trainings- en testset overlappen. Stoppen.")
    if len(train) < 10 or len(test) < 10:
        raise SystemExit(f"Te weinig labels (train={len(train)}, test={len(test)}).")

    # Taal en keyword-basislijn voor de testset
    meta = pd.read_parquet(args.test_meta, columns=["vacancy_id", "lang", "keyword_has_ai"])
    meta["vacancy_id"] = meta["vacancy_id"].astype(str)
    test = test.merge(meta, on="vacancy_id", how="left")
    test["lang"] = test["lang"].fillna("unknown")
    test["keyword_has_ai"] = test["keyword_has_ai"].fillna(False).astype(bool)

    print(f"\nTraining op {len(train)} labels, verdeling: "
          f"{train['ai_type'].value_counts().to_dict()}")
    w = training_weights(train, args.label_sample)
    X_train = vecs[[index[v] for v in train["vacancy_id"]]]
    X_test = vecs[[index[v] for v in test["vacancy_id"]]]

    model = LogisticRegression(C=args.C, max_iter=5000, random_state=SEED)
    model.fit(X_train, train["ai_type"].astype(str).to_numpy(), sample_weight=w)

    pred_test = model.predict(X_test)
    evaluate(test, pred_test, test["keyword_has_ai"].to_numpy())

    all_ids = list(index.keys())
    tags = build_tags(all_ids, vecs, model)
    print("\nVerdeling ai_type over alle embeddings (model):")
    print(tags["ai_type"].value_counts().to_string())

    if args.no_write:
        print("\n--no-write: tags.parquet niet weggeschreven.")
        return
    write_tags(tags, args.out)


if __name__ == "__main__":
    main()
