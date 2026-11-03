"""Maakt de twee samplebestanden voor slice B.

1. label_sample_1500.parquet : ~1.500 vacatures om door Claude te laten labelen.
   Gespreid over land, taal en jaar. Vacatures met een keyword-hit krijgen
   extra gewicht (AI is zeldzaam). Kolom inclusion_prob = kans dat een
   vacature in deze set kwam; de trainer gebruikt 1/inclusion_prob als gewicht.
2. test_set_300.parquet      : onafhankelijke testset van 300 vacatures.
   Natuurlijke verdeling (geen weging), gespreid over land, taal en jaar.
   Deze set wordt eerst getrokken en daarna uit de labelset gehouden, zodat
   er geen overlap is. Nooit gebruiken voor training of voor de prompt.

Seed 42. Paden komen uit common/paths.py.

Draaien:
  python prepare_samples.py [--sample PAD] [--spine PAD] [--label-out PAD] [--test-out PAD]
"""

import argparse
import re
import sys
from pathlib import Path

import numpy as np
import pandas as pd

# common/ staat één map boven tagging/ (de repo-root). baseline.py staat in
# dezelfde map en wordt hieronder geïmporteerd.
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
sys.path.insert(0, str(Path(__file__).resolve().parent))

from baseline import add_ai_columns  # noqa: E402
from common.paths import (  # noqa: E402
    LABEL_SAMPLE_PARQUET,
    SAMPLE_PARQUET,
    SPINE_PARQUET,
    TEST_SET_PARQUET,
)

SEED = 42
STRATA = ["country", "lang", "year"]
# Alleen de labelset krijgt extra gewicht voor deze landen (testset blijft natuurlijk).
OVERSAMPLE_COUNTRIES = ("BE", "NL")
DEFAULT_OVERSAMPLE_WEIGHT = 2.5

# Heuristiek voor taal, alleen gebruikt als er geen spine met 'lang' is.
_STOPWORDS = {
    "en": {"the", "and", "with", "you", "will", "for", "our", "are", "of", "to", "this", "we"},
    "nl": {"en", "het", "een", "je", "wij", "voor", "met", "van", "bij", "dat", "zijn", "onze"},
    "fr": {"et", "le", "la", "les", "des", "vous", "avec", "pour", "nous", "une", "est", "dans"},
    "de": {"und", "der", "das", "mit", "für", "wir", "sie", "ein", "eine", "ist", "zu", "nicht"},
}


def detect_lang(text: str) -> str:
    """Grove taalschatting op basis van stopwoorden. Geeft en|nl|fr|de|other."""
    words = re.findall(r"[^\W\d_]+", (text or "").lower())
    if not words:
        return "other"
    scores = {lang: sum(w in sw for w in words) for lang, sw in _STOPWORDS.items()}
    best = max(scores, key=scores.get)
    return best if scores[best] >= 3 else "other"


def prepare(df: pd.DataFrame, spine_path: Path) -> pd.DataFrame:
    """Voegt country, lang, year en de keyword-labels toe."""
    out = df.copy()
    out["country"] = out["country"].fillna("unknown").astype(str)
    out["year"] = (
        pd.to_datetime(out["date_posted"], errors="coerce").dt.year.map(
            lambda y: "unknown" if pd.isna(y) else str(int(y))
        )
    )

    # Taal uit de spine (slice A) als die bestaat, anders de heuristiek.
    lang_from_spine = None
    if spine_path.exists():
        spine = pd.read_parquet(spine_path, columns=["vacancy_id", "lang"])
        lang_from_spine = spine.drop_duplicates("vacancy_id").set_index("vacancy_id")["lang"]
    if lang_from_spine is not None:
        out["lang"] = out["vacancy_id"].map(lang_from_spine)
        out["lang"] = out["lang"].fillna("other").astype(str)
        print(f"Taal uit spine: {spine_path}")
    else:
        combined = out["title"].fillna("") + " " + out["text"].fillna("")
        out["lang"] = combined.map(detect_lang)
        print("Taal via heuristiek (geen spine gevonden).")

    tagged = add_ai_columns(out)
    out["keyword_has_ai"] = tagged["has_ai"].astype(bool).values
    out["keyword_ai_type"] = tagged["ai_type"].astype(str).values
    return out


def _allocate(sizes: pd.Series, n: int, weights: pd.Series) -> pd.Series:
    """Verdeelt n over de groepen naar rato van grootte * gewicht (largest remainder).

    Het aantal per groep is nooit groter dan de groepsgrootte zelf.
    """
    eff = sizes * weights
    total = float(eff.sum())
    n = min(n, int(sizes.sum()))
    raw = eff * (n / total)
    base = np.floor(raw).astype(int)
    short = n - int(base.sum())
    order = (raw - base).sort_values(ascending=False, kind="stable").index
    base.loc[order[:short]] += 1
    return np.minimum(base, sizes).astype(int)


def _stratified(df: pd.DataFrame, n: int, oversample_weight: float = 1.0) -> pd.DataFrame:
    """Trekt n rijen, gespreid over STRATA.

    BE- en NL-groepen krijgen gewicht oversample_weight (1.0 = geen oversampling).
    Kolom inclusion_prob = k / groepsgrootte, dus de kans dat een rij gekozen is.
    Vult aan met willekeurige rijen als een groep te klein is (dan geen exacte kans).
    """
    if n <= 0 or df.empty:
        return df.iloc[0:0]
    sizes = df.groupby(STRATA).size()
    countries = pd.Series(sizes.index.get_level_values("country"), index=sizes.index)
    weights = countries.map(
        lambda c: oversample_weight if c in OVERSAMPLE_COUNTRIES else 1.0
    ).astype(float)
    alloc = _allocate(sizes, n, weights).to_dict()

    parts = []
    for key, group in df.groupby(STRATA, sort=True):
        k = alloc.get(key, 0)
        if k:
            chosen = group.sample(n=k, random_state=SEED).copy()
            chosen["inclusion_prob"] = k / len(group)
            parts.append(chosen)
    out = pd.concat(parts) if parts else df.iloc[0:0].copy()

    missing = min(n, len(df)) - len(out)
    if missing > 0:
        pool = df.drop(index=out.index)
        extra = pool.sample(n=missing, random_state=SEED).copy()
        extra["inclusion_prob"] = missing / len(pool)
        out = pd.concat([out, extra])
    return out


def make_samples(
    df: pd.DataFrame,
    n_label: int,
    n_test: int,
    hit_share: float,
    oversample_weight: float,
):
    """Geeft (label_set, test_set). Testset eerst (natuurlijke verdeling, geen weging), daarna labelset uit de rest."""
    test = _stratified(df, n_test, oversample_weight=1.0)

    rest = df.drop(index=test.index)
    rest_hit = rest[rest["keyword_has_ai"]]
    rest_non = rest[~rest["keyword_has_ai"]]

    n_hit = min(round(n_label * hit_share), len(rest_hit))
    n_non = min(n_label - n_hit, len(rest_non))
    lab_hit = _stratified(rest_hit, n_hit, oversample_weight=oversample_weight)
    lab_non = _stratified(rest_non, n_non, oversample_weight=oversample_weight)

    label = pd.concat([lab_hit, lab_non]).copy()

    # Controles: geen overlap, geen dubbele ids.
    assert set(test.index).isdisjoint(set(label.index)), "testset overlapt labelset"
    assert test["vacancy_id"].is_unique and label["vacancy_id"].is_unique
    assert set(test["vacancy_id"]).isdisjoint(set(label["vacancy_id"]))

    return label, test


def _keep(df: pd.DataFrame, extra: list[str]) -> pd.DataFrame:
    cols = ["vacancy_id", "title", "text", "country", "lang", "year",
            "date_posted", "keyword_has_ai", "keyword_ai_type"] + extra
    return df[cols].reset_index(drop=True)


def parse_args(argv=None) -> argparse.Namespace:
    p = argparse.ArgumentParser(description="Maakt label- en testsample (slice B).")
    p.add_argument("--sample", type=Path, default=SAMPLE_PARQUET)
    p.add_argument("--spine", type=Path, default=SPINE_PARQUET,
                   help="Optioneel: spine.parquet voor de taalkolom")
    p.add_argument("--label-out", type=Path, default=LABEL_SAMPLE_PARQUET)
    p.add_argument("--test-out", type=Path, default=TEST_SET_PARQUET)
    p.add_argument("--n-label", type=int, default=1500)
    p.add_argument("--n-test", type=int, default=300)
    p.add_argument("--hit-share", type=float, default=0.5,
                   help="Aandeel keyword-hits in de labelset (0-1)")
    p.add_argument("--oversample-weight", type=float, default=DEFAULT_OVERSAMPLE_WEIGHT,
                   help="Gewicht voor BE/NL in de labelset (2-3 aanbevolen; 1.0 = geen)")
    return p.parse_args(argv)


def main(argv=None) -> None:
    args = parse_args(argv)
    df = pd.read_parquet(args.sample).reset_index(drop=True)
    print(f"Sample ingelezen: {len(df)} rijen uit {args.sample}")

    df = prepare(df, args.spine)
    label, test = make_samples(
        df, args.n_label, args.n_test, args.hit_share, args.oversample_weight
    )

    label_out = _keep(label, ["inclusion_prob"])
    test_out = _keep(test, [])
    args.label_out.parent.mkdir(parents=True, exist_ok=True)
    label_out.to_parquet(args.label_out, index=False)
    test_out.to_parquet(args.test_out, index=False)

    print(f"\nLabelset: {len(label_out)} rijen -> {args.label_out}")
    print(f"  keyword-hits: {int(label_out['keyword_has_ai'].sum())}")
    print(f"Testset:   {len(test_out)} rijen -> {args.test_out}")
    print(f"  keyword-hits: {int(test_out['keyword_has_ai'].sum())}")
    print("\nVerdeling labelset per land:\n", label_out["country"].value_counts().to_string())
    print("\nVerdeling labelset per taal:\n", label_out["lang"].value_counts().to_string())
    print("\nVerdeling labelset per jaar:\n", label_out["year"].value_counts().sort_index().to_string())


if __name__ == "__main__":
    main()
