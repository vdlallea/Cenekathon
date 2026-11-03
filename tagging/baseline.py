"""AI-tag basislijn voor AI Talent Radar (slice B).

Leest de sample van 20k vacatures, voegt has_ai en ai_type toe op basis van
de AI-woordenlijst, en schrijft het contract tags.parquet:
  vacancy_id (str), has_ai (bool), ai_type (str),
  confidence (float, 1.0), source (str, "keyword")

Regel bij twijfel (meerdere types): bouwer > bewaker > gebruiker.

Paden komen uit common/paths.py. Overschrijven kan met argumenten:
  python baseline.py --sample <pad> --out <pad>
"""

import argparse
import re
import sys
from pathlib import Path

import pandas as pd

# common/ staat één map boven tagging/ (de repo-root).
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from common.paths import SAMPLE_PARQUET, TAGS_PARQUET  # noqa: E402

# --- AI-woordenlijst ----------------------------------------------------------
# Patronen zijn regex en worden toegepast op kleine letters.
# Volgorde in de logica hieronder = prioriteit (bouwer > bewaker > gebruiker).

BUILDER_PATTERNS = [
    r"machine learning",
    r"deep learning",
    r"computer vision",
    r"\bnlp\b",
    r"\bllms?\b",
    r"large language models?",
    r"\bmlops\b",
    r"\bml engineer",
    r"\bai engineer",
    r"\bai/ml\b",
    r"data scientist",
    r"model training",
]

GOVERNOR_PATTERNS = [
    r"ai[- ]governance",
    r"responsible ai",
    r"\beu ai act\b",
    r"\bai act\b",
    r"ai[- ]audit",
    r"ai[- ]ethic",
    r"ai[- ]risk",
]

# "Model risk" telt alleen als bewaker wanneer AI of ML expliciet in de
# vacature staat. Klassieke kredietmodelvalidatie (zonder AI/ML) telt niet.
MODEL_RISK_PATTERNS = [
    r"model[- ]?risk",
    r"model[- ]?risico",
]
EXPLICIT_AI_ML_PATTERNS = [
    r"\bai\b",
    r"\bml\b",
    r"machine learning",
    r"artificial intelligence",
    r"kunstmatige intelligentie",
]

USER_PATTERNS = [
    r"copilot",
    r"chatgpt",
    r"\bai[- ]tools?\b",
    r"prompt engineering",
    r"ai[- ]assistent",
]

# Algemene AI-termen: tellen mee voor has_ai, maar leggen het type niet vast.
GENERIC_PATTERNS = [
    r"generative ai",
    r"\bgen(?:erative)? ai\b",
    r"\bgenai\b",
    r"artificial intelligence",
    r"kunstmatige intelligentie",
]


# --- Logica -------------------------------------------------------------------
def _matches(text: str, patterns: list[str]) -> bool:
    return any(re.search(p, text) for p in patterns)


def _model_risk_counts(text: str) -> bool:
    """Model risk telt alleen als AI of ML er expliciet bij staat."""
    return _matches(text, MODEL_RISK_PATTERNS) and _matches(
        text, EXPLICIT_AI_ML_PATTERNS
    )


def tag_text(text: str) -> tuple[bool, str]:
    """Geeft (has_ai, ai_type) terug voor één tekst."""
    t = text.lower()
    if _matches(t, BUILDER_PATTERNS):
        return True, "builder"
    if _matches(t, GOVERNOR_PATTERNS) or _model_risk_counts(t):
        return True, "governor"
    if _matches(t, USER_PATTERNS):
        return True, "user"
    # Alleen algemene AI-termen: AI is genoemd, maar het type is onduidelijk.
    # Fallback naar "user": een algemene AI-vermelding past het best bij
    # een niet-AI-functie die AI gebruikt.
    if _matches(t, GENERIC_PATTERNS):
        return True, "user"
    return False, "none"


def add_ai_columns(frame: pd.DataFrame) -> pd.DataFrame:
    """Voegt has_ai en ai_type toe op basis van title + text."""
    combined = frame["title"].fillna("") + " " + frame["text"].fillna("")
    results = combined.map(tag_text)
    out = frame.copy()
    out["has_ai"] = results.map(lambda r: r[0]).astype(bool)
    out["ai_type"] = results.map(lambda r: r[1])
    return out


def build_tags(frame: pd.DataFrame) -> pd.DataFrame:
    """Maakt het contract-dataframe tags.parquet."""
    tagged = add_ai_columns(frame)
    return pd.DataFrame(
        {
            "vacancy_id": tagged["vacancy_id"].astype(str),
            "has_ai": tagged["has_ai"].astype(bool),
            "ai_type": tagged["ai_type"].astype(str),
            "confidence": pd.Series(1.0, index=tagged.index, dtype="float64"),
            "source": pd.Series("keyword", index=tagged.index, dtype="object"),
        }
    )


def _self_check() -> None:
    """Controleert de prioriteitsregel en de belangrijkste gevallen."""
    assert tag_text("machine learning en copilot") == (True, "builder")
    assert tag_text("ai governance en copilot") == (True, "governor")
    assert tag_text("copilot en chatgpt") == (True, "user")
    assert tag_text("generative ai ervaring") == (True, "user")
    assert tag_text("boekhouding en rapportage") == (False, "none")
    # Model risk: alleen met expliciet AI of ML
    assert tag_text("model risk management en AI-tools") == (True, "governor")
    assert tag_text("model risk en machine learning") == (True, "builder")
    assert tag_text("model risk validatie van kredietmodellen") == (False, "none")
    assert tag_text("kredietmodelvalidatie en model risk rapportage") == (
        False,
        "none",
    )


def parse_args(argv=None) -> argparse.Namespace:
    p = argparse.ArgumentParser(description="AI-tag basislijn (keyword).")
    p.add_argument("--sample", type=Path, default=SAMPLE_PARQUET,
                   help="Invoer: sample-parquet (standaard uit common/paths.py)")
    p.add_argument("--out", type=Path, default=TAGS_PARQUET,
                   help="Uitvoer: tags.parquet (standaard uit common/paths.py)")
    return p.parse_args(argv)


def main(argv=None) -> None:
    args = parse_args(argv)
    _self_check()

    sample = pd.read_parquet(args.sample)
    print(f"Sample ingelezen: {len(sample)} rijen uit {args.sample}")

    tags = build_tags(sample)
    args.out.parent.mkdir(parents=True, exist_ok=True)
    tags.to_parquet(args.out, index=False)
    print(f"Geschreven: {args.out} ({len(tags)} rijen)")
    print(tags.dtypes)

    print("\nValue counts ai_type:")
    print(tags["ai_type"].value_counts())


if __name__ == "__main__":
    main()
