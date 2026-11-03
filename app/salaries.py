"""Salarissen uit UK-vacatures halen via regex (slice D, SPEC.md: contract salaries.parquet).

Herkende vormen (voorbeelden):
  "£55,000 - £65,000"  "£55k-£65k"  "up to £70,000"  "£300 per day"  "£25 per hour"

Alles wordt omgezet naar jaarsalaris in GBP: dag x DAYS_PER_YEAR, uur x HOURS_PER_YEAR
(zie assumptions.py). De oorspronkelijke eenheid komt in de kolom `period`.
Een enkel bedrag geeft salary_min == salary_max.

Draaien:
  python app/salaries.py pad/naar/spine.parquet
"""

import argparse
import re
import sys
from dataclasses import dataclass
from pathlib import Path

import pandas as pd

from assumptions import DAYS_PER_YEAR, HOURS_PER_YEAR, MIN_UNITLESS_ANNUAL_GBP

CURRENCY = "GBP"
COLUMNS = ["vacancy_id", "company_id", "salary_min", "salary_max", "currency", "period"]
PERIOD_FACTOR = {"year": 1, "day": DAYS_PER_YEAR, "hour": HOURS_PER_YEAR}
UNIT_TO_PERIOD = {"annum": "year", "year": "year", "yr": "year", "day": "day", "hour": "hour", "hr": "hour"}
# Maand en week hebben geen omrekening in de spec: deze vacatures worden overgeslagen.
UNSUPPORTED_UNITS = {"month", "week"}


# --- Regex --------------------------------------------------------------------
# Bedrag met verplicht £-teken: "£55,000", "£55k", "£300", "£55.5k".
# Het k-achtervoegsel is een aparte groep, zodat "£55k" -> 55000 wordt.
def _amount(tag: str, pound_required: bool) -> str:
    pound = r"£\s*" if pound_required else r"£?\s*"
    return (
        rf"{pound}(?P<{tag}>\d{{1,3}}(?:,\d{{3}})+(?:\.\d+)?|\d+(?:\.\d+)?)"
        rf"(?:\s*(?P<{tag}_k>[kK])\b)?"
    )


# Eenheid na het bedrag: "per day", "a year", "/hour", "per annum".
_UNIT = r"(?:\s*(?:per|a|an|/)\s*(?P<unit>annum|year|yr|day|hour|hr|month|week)\b)?"

_RANGE_RE = re.compile(
    _amount("lo", pound_required=True) + r"\s*(?:-|–|—|to)\s*" + _amount("hi", pound_required=False) + _UNIT,
    re.IGNORECASE,
)
_SINGLE_RE = re.compile(
    r"(?:up to\s+|upto\s+|from\s+)?" + _amount("one", pound_required=True) + _UNIT,
    re.IGNORECASE,
)


# --- Logica -------------------------------------------------------------------
@dataclass(frozen=True)
class Salary:
    salary_min: float  # jaarsalaris in GBP
    salary_max: float  # jaarsalaris in GBP
    period: str  # oorspronkelijke eenheid: year | day | hour


def _to_number(raw: str, k_suffix: str | None) -> float:
    value = float(raw.replace(",", ""))
    return value * 1000 if k_suffix else value


def _build(lo: float, hi: float, unit: str | None) -> Salary | None:
    unit = unit.lower() if unit else None
    if unit in UNSUPPORTED_UNITS:
        return None
    if unit is None:
        # Zonder eenheid alleen als jaarsalaris, en alleen boven de ondergrens.
        if min(lo, hi) < MIN_UNITLESS_ANNUAL_GBP:
            return None
        period = "year"
    else:
        period = UNIT_TO_PERIOD[unit]
    factor = PERIOD_FACTOR[period]
    lo, hi = sorted((lo, hi))
    return Salary(salary_min=lo * factor, salary_max=hi * factor, period=period)


def parse_salary(text: object) -> Salary | None:
    """Geeft het eerste herkende salaris in de tekst terug, of None."""
    if not isinstance(text, str) or not text.strip():
        return None
    # Bereiken eerst. Een bereik dat we niet kunnen omrekenen (bv. per maand)
    # blokkeert de enkele-bedragen erin, anders wordt "£10,000" los als jaarsalaris gelezen.
    spans = []
    for m in _RANGE_RE.finditer(text):
        spans.append(m.span())
        result = _build(_to_number(m["lo"], m["lo_k"]), _to_number(m["hi"], m["hi_k"]), m["unit"])
        if result is not None:
            return result
    for m in _SINGLE_RE.finditer(text):
        if any(start <= m.start() < end for start, end in spans):
            continue
        value = _to_number(m["one"], m["one_k"])
        result = _build(value, value, m["unit"])
        if result is not None:
            return result
    return None


def extract_salaries(frame: pd.DataFrame) -> pd.DataFrame:
    """Vacatures met gevonden salaris, in het contractformaat salaries.parquet.

    Verwacht de kolommen vacancy_id, company_id, title en text.
    Doorzoekt title + text, zodat een salaris in de titel ook meetelt.
    """
    combined = frame["title"].fillna("").astype(str) + " " + frame["text"].fillna("").astype(str)
    rows = []
    for vacancy_id, company_id, text in zip(frame["vacancy_id"], frame["company_id"], combined):
        salary = parse_salary(text)
        if salary is None:
            continue
        rows.append({
            "vacancy_id": str(vacancy_id),
            "company_id": str(company_id),
            "salary_min": salary.salary_min,
            "salary_max": salary.salary_max,
            "currency": CURRENCY,
            "period": salary.period,
        })
    out = pd.DataFrame(rows, columns=COLUMNS)
    return out.astype({"vacancy_id": "str", "company_id": "str", "salary_min": "float64",
                       "salary_max": "float64", "currency": "str", "period": "str"})


def coverage_pct(n_found: int, n_total: int) -> float:
    return 100.0 * n_found / n_total if n_total else 0.0


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Salarissen uit UK-vacatures (regex).")
    parser.add_argument("parquet", type=Path, help="pad naar spine.parquet")
    args = parser.parse_args(argv)

    frame = pd.read_parquet(args.parquet, columns=["vacancy_id", "company_id", "country", "title", "text"])
    gb = frame[frame["country"] == "GB"]
    salaries = extract_salaries(gb)

    pct = coverage_pct(len(salaries), len(gb))
    print(f"UK-vacatures: {len(gb):,}")
    print(f"Met gevonden salaris: {len(salaries):,} ({pct:.1f}%)")
    return 0


if __name__ == "__main__":
    sys.exit(main())
