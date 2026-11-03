"""AI-tag basislijn voor AI Talent Radar (slice B).

Leest de sample van 20k vacatures, voegt has_ai en ai_type toe op basis van
de AI-woordenlijst, en schrijft het contract tags.parquet:
  vacancy_id (str), has_ai (bool), ai_type (str),
  confidence (float, 1.0), source (str, "keyword")

Regel bij twijfel (meerdere types): bouwer > bewaker > gebruiker.

Draaien (op de server, in de venv):
  python baseline.py
Pad naar de sample kan worden overschreven met de env-var SAMPLE_PATH.
"""

import os
import re
from pathlib import Path

import pandas as pd

# --- Paden --------------------------------------------------------------------
# Sample staat op de server in de gedeelde map ~/data/work/ (team6).
SAMPLE_PATH = Path(
    os.environ.get("SAMPLE_PATH", "/home/team6/data/work/sample_20k.parquet")
)
# ../data/work/tags.parquet ten opzichte van deze map (tagging/).
TAGS_PATH = Path(__file__).resolve().parent.parent / "data" / "work" / "tags.parquet"

# --- AI-woordenlijst ----------------------------------------------------------
# Patronen zijn regex en worden toegepast op kleine letters.
# Volgorde in TYPE_PATTERNS = prioriteit (bouwer > bewaker > gebruiker).

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

# Volgorde = prioriteit bij meerdere types.
TYPE_PATTERNS = [
    ("builder", BUILDER_PATTERNS),
    ("governor", GOVERNOR_PATTERNS),
    ("user", USER_PATTERNS),
]


# --- Logica -------------------------------------------------------------------
def _matches(text: str, patterns: list[str]) -> bool:
    return any(re.search(p, text) for p in patterns)


def tag_text(text: str) -> tuple[bool, str]:
    """Geeft (has_ai, ai_type) terug voor één tekst."""
    t = text.lower()
    for ai_type, patterns in TYPE_PATTERNS:
        if _matches(t, patterns):
            return True, ai_type
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


if __name__ == "__main__":
    _self_check()

    sample = pd.read_parquet(SAMPLE_PATH)
    print(f"Sample ingelezen: {len(sample)} rijen uit {SAMPLE_PATH}")

    tags = build_tags(sample)
    TAGS_PATH.parent.mkdir(parents=True, exist_ok=True)
    tags.to_parquet(TAGS_PATH, index=False)
    print(f"Geschreven: {TAGS_PATH} ({len(tags)} rijen)")
    print(tags.dtypes)

    print("\nValue counts ai_type:")
    print(tags["ai_type"].value_counts())
