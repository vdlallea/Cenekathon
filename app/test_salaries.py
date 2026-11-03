"""Zelftest voor app/salaries.py op handgeschreven voorbeeldzinnen. Geen data nodig.

    python app/test_salaries.py
"""

import pandas as pd

from assumptions import DAYS_PER_YEAR, HOURS_PER_YEAR
from salaries import COLUMNS, Salary, coverage_pct, extract_salaries, parse_salary

# (zin, verwacht) — verwacht is (min, max, period) of None als er geen salaris gevonden mag worden.
EXAMPLES = [
    ("Salary: £55,000 - £65,000 per annum", (55_000, 65_000, "year")),
    ("Pay: £55k-£65k", (55_000, 65_000, "year")),
    ("Competitive package, up to £70,000", (70_000, 70_000, "year")),
    ("Day rate £300 per day, inside IR35", (300 * DAYS_PER_YEAR, 300 * DAYS_PER_YEAR, "day")),
    ("Contract paying £25 per hour", (25 * HOURS_PER_YEAR, 25 * HOURS_PER_YEAR, "hour")),
    ("Salary £45,000 per annum plus bonus", (45_000, 45_000, "year")),
    ("Starting at £60k a year", (60_000, 60_000, "year")),
    ("Interim role, £400 a day", (400 * DAYS_PER_YEAR, 400 * DAYS_PER_YEAR, "day")),
    ("Temp position at £30 an hour", (30 * HOURS_PER_YEAR, 30 * HOURS_PER_YEAR, "hour")),
    ("Rate £25 - 30 per hour", (25 * HOURS_PER_YEAR, 30 * HOURS_PER_YEAR, "hour")),
    ("£65k - £55k, hybrid working", (55_000, 65_000, "year")),
    ("Ideal for 5 years experience, £50,000 salary", (50_000, 50_000, "year")),
    ("Salary up to £70k", (70_000, 70_000, "year")),
    # Geen salaris: niets vinden is ook een geldig resultaat.
    ("Competitive salary, no figures given", None),
    ("We offer 25 days holiday and £300 vouchers", None),
    ("Graduate scheme with a fixed stipend", None),
    # Maand en week worden niet omgerekend, dus geen salaris.
    ("£2,000 - £3,000 per month", None),
    ("£10,000 - £12,000 per month", None),
    ("Pay £3,500 a month", None),
]


def test_examples() -> None:
    for sentence, expected in EXAMPLES:
        got = parse_salary(sentence)
        if expected is None:
            assert got is None, (sentence, got)
            continue
        assert got == Salary(*expected), (sentence, got, expected)


def test_range_blocks_single_amount() -> None:
    # Het eerste bedrag van een niet-omrekenbaar bereik mag niet los als jaarsalaris tellen.
    assert parse_salary("£10,000 - £12,000 per month") is None


def test_empty_and_missing_text() -> None:
    assert parse_salary(None) is None
    assert parse_salary("") is None
    assert parse_salary("   ") is None
    assert parse_salary(float("nan")) is None


def test_extract_salaries_contract() -> None:
    frame = pd.DataFrame({
        "vacancy_id": ["v1", "v2", "v3"],
        "company_id": ["kbc", "ing", "ing"],
        "title": ["Data analyst", "Engineer £45k", None],
        "text": ["Pay: £55,000 - £65,000", None, "No salary here"],
    })
    out = extract_salaries(frame)
    assert list(out.columns) == COLUMNS, out.columns
    assert out["vacancy_id"].tolist() == ["v1", "v2"]
    assert out["period"].tolist() == ["year", "year"]
    assert out["currency"].eq("GBP").all()
    assert out.loc[0, "salary_min"] == 55_000 and out.loc[0, "salary_max"] == 65_000
    assert out.loc[1, "salary_min"] == 45_000 and out.loc[1, "salary_max"] == 45_000
    assert str(out["salary_min"].dtype) == "float64"


def test_extract_salaries_empty() -> None:
    frame = pd.DataFrame({"vacancy_id": [], "company_id": [], "title": [], "text": []})
    out = extract_salaries(frame)
    assert list(out.columns) == COLUMNS and len(out) == 0


def test_coverage_pct() -> None:
    assert coverage_pct(1, 4) == 25.0
    assert coverage_pct(0, 0) == 0.0


def test_main_writes_contract_file(tmp_path=None) -> None:
    import tempfile
    from pathlib import Path

    from salaries import main

    with tempfile.TemporaryDirectory() as tmp:
        tmp = Path(tmp)
        spine = tmp / "spine.parquet"
        out = tmp / "sub" / "salaries.parquet"
        pd.DataFrame({
            "vacancy_id": ["v1", "v2", "v3"],
            "company_id": ["kbc", "ing", "ing"],
            "country": ["GB", "GB", "BE"],
            "title": ["Analyst", "Engineer", "Analyst"],
            "text": ["Pay: £55,000 - £65,000", "Day rate £300 per day", "£60,000 per annum"],
        }).to_parquet(spine, index=False)
        assert main([str(spine), "--out", str(out)]) == 0
        written = pd.read_parquet(out)
        assert list(written.columns) == COLUMNS, written.columns
        # Alleen UK-vacatures tellen mee; v3 (BE) valt weg.
        assert written["vacancy_id"].tolist() == ["v1", "v2"]
        assert written.loc[1, "salary_min"] == 300 * DAYS_PER_YEAR


if __name__ == "__main__":
    tests = [test_examples, test_range_blocks_single_amount, test_empty_and_missing_text,
             test_extract_salaries_contract, test_extract_salaries_empty, test_coverage_pct,
             test_main_writes_contract_file]
    for t in tests:
        t()
        print(f"OK  {t.__name__}")
    print(f"Alle {len(tests)} testfuncties geslaagd ({len(EXAMPLES)} voorbeeldzinnen).")
