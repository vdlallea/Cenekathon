"""Zelftest voor app/advice.py op stubs. Geen API-call, geen netwerk, geen schrijfacties.

    python app/test_advice.py
"""

import json

import pandas as pd

from advice import (
    NoData,
    build_prompt,
    cfg,
    compute_metrics,
    cost_options,
    load_inputs,
    parse_llm,
    salary_basis,
    number_items,
    template_card,
    unknown_numbers,
    window_quarters,
)

CQ, PEERS, SALARIES = load_inputs(use_stubs=True)
QUARTERS = window_quarters(CQ)


def _metrics(company: str, salaries=SALARIES):
    return compute_metrics(company, CQ, PEERS, salaries, QUARTERS)


def test_window_is_last_clean_quarters() -> None:
    # 2026Q1-Q2 zijn het gat; de laatste vier schone kwartalen blijven over.
    assert len(QUARTERS) == 4
    assert "2026Q1" not in QUARTERS and "2026Q2" not in QUARTERS
    assert QUARTERS[-1] == "2026Q3"


def test_number_check_accepts_and_rejects() -> None:
    allowed = {6.0, 3.0, 450000.0, 1840.0, 4.0}
    assert unknown_numbers("6,0% en 3× en €450.000 over 4 kwartalen", allowed) == []
    assert unknown_numbers("1.840 vacatures", allowed) == []
    assert unknown_numbers("7% van de vacatures", allowed) == ["7"]
    assert unknown_numbers("kost €460.000", allowed) == ["460.000"]
    # Kwartaalnamen en getallen in letters (ingebed in woorden) tellen niet als getal.
    assert unknown_numbers("sinds 2025Q4", allowed) == []


def test_cost_options() -> None:
    costs = cost_options(5, 60_000)
    assert costs["aanwerven"] == round(5 * 60_000 * cfg("RECRUIT_COST_PCT"))  # 60.000
    assert costs["omscholen"] == 5 * cfg("TRAINING_COST_EUR")  # 20.000


def test_salary_fallback_and_median() -> None:
    few = pd.DataFrame({"salary_min": [50_000.0] * 5})
    value, source, n = salary_basis(few)
    assert (value, source, n) == (cfg("FALLBACK_SALARY_EUR"), "aanname", 5)

    enough = pd.DataFrame({"salary_min": [50_000.0] * 40})
    value, source, n = salary_basis(enough)
    assert source == "mediaan" and n == 40
    assert abs(value - 50_000 * cfg("GBP_TO_EUR")) < 1e-6

    value, source, n = salary_basis(None)
    assert (source, n) == ("aanname", 0)


def test_metrics_for_all_stub_companies() -> None:
    companies = sorted(CQ["company_id"].unique())
    for company in companies:
        try:
            m = _metrics(company)
        except NoData:
            continue
        assert m["n_bank"] > 0 and m["n_peers"] > 0
        assert 0 <= m["share_ai_bank"] <= 1 and 0 <= m["share_ai_peer"] <= 1
        assert 0 <= m["profielen_per_kwartaal"] <= cfg("MAX_PROFILES_PER_QUARTER")
        if m["grootste_type"] is None:
            assert m["profielen_per_kwartaal"] == 0
        else:
            assert m["achterstand_grootste"] > 0


def test_profiles_cap() -> None:
    # Een enorme achterstand moet op de bovengrens blijven hangen.
    cq = CQ.copy()
    cq.loc[cq["company_id"] == "kbc", "share_governor"] = 0.0
    cq.loc[cq["company_id"] != "kbc", "share_governor"] = 0.9
    m = compute_metrics("kbc", cq, PEERS, SALARIES, QUARTERS)
    assert m["grootste_type"] == "governor"
    assert m["profielen_per_kwartaal"] == cfg("MAX_PROFILES_PER_QUARTER")


def test_template_uses_only_inputs() -> None:
    # De template mag alleen getallen gebruiken die ook in de prompt staan.
    for company in sorted(CQ["company_id"].unique()):
        try:
            m = _metrics(company)
        except NoData:
            continue
        costs = cost_options(m["profielen_per_kwartaal"], m["salaris_eur"])
        allowed = {float(value) for _, value in number_items(m, costs)}
        card = template_card(m, costs)
        text = " ".join([card["headline"]] + [a["advice"] for a in card["actions"]])
        assert unknown_numbers(text, allowed) == [], (company, text)


def test_prompt_lists_all_numbers() -> None:
    company = next(c for c in sorted(CQ["company_id"].unique()) if _has_gap(c))
    m = _metrics(company)
    costs = cost_options(m["profielen_per_kwartaal"], m["salaris_eur"])
    prompt, items = build_prompt(company, m, costs)
    assert len(items) >= 20
    for label, value in items:
        assert f"- {label}: {value}" in prompt
        assert not value.startswith("-"), (label, value)  # geen teken dat het model kan verliezen


def test_generate_card_with_fake_llm() -> None:
    # Neppe Haiku-call: controleert de drie uitkomsten zonder netwerk.
    import advice

    company = next(c for c in sorted(CQ["company_id"].unique())
                   if _has_gap(c))
    m = _metrics(company)
    costs = cost_options(m["profielen_per_kwartaal"], m["salaris_eur"])
    prompt, items = build_prompt(company, m, costs)
    p = m["profielen_per_kwartaal"]
    fallback = template_card(m, costs)
    original = advice.call_haiku
    try:
        # 1. Goede output: tekst komt uit het model, kosten komen uit Python.
        good = json.dumps({"headline": f"{company.upper()} loopt achter",
                           "actions": [{"advice": f"Werf {p} profielen aan", "optie": "aanwerven"}]})
        advice.call_haiku = lambda prompt, cid: good
        card = advice.generate_card(m, costs, prompt, items)
        assert card["headline"] == f"{company.upper()} loopt achter"
        assert card["actions"] == [{"advice": f"Werf {p} profielen aan", "cost_eur": costs["aanwerven"]}]

        # 2. Verzonnen getal (7 is nooit in de invoer): terugval op de template.
        bad = json.dumps({"headline": "x", "actions": [{"advice": "Werf 7 profielen", "optie": "aanwerven"}]})
        advice.call_haiku = lambda prompt, cid: bad
        assert advice.generate_card(m, costs, prompt, items) == fallback

        # 3. API-fout: ook de template, geen crash.
        def boom(prompt, cid):
            raise RuntimeError("netwerk")
        advice.call_haiku = boom
        assert advice.generate_card(m, costs, prompt, items) == fallback
    finally:
        advice.call_haiku = original


def _has_gap(company: str) -> bool:
    try:
        return _metrics(company)["grootste_type"] is not None
    except NoData:
        return False


def test_parse_llm_rules() -> None:
    good = {"headline": "KBC loopt achter", "actions": [{"advice": "Werf 5 profielen", "optie": "aanwerven"}]}
    assert parse_llm(json.dumps(good)) is not None
    assert parse_llm("Hier is het: " + json.dumps(good) + " Klaar.") is not None
    assert parse_llm("geen json") is None
    assert parse_llm('{"headline": "x", "actions": []}') is None
    assert parse_llm(json.dumps({"headline": "x", "actions": [{"advice": "y", "optie": "kopen"}]})) is None
    assert parse_llm(json.dumps({"headline": "", "actions": [{"advice": "y", "optie": "omscholen"}]})) is None
    four = [{"advice": "y", "optie": "omscholen"}] * 4
    assert parse_llm(json.dumps({"headline": "x", "actions": four})) is None


if __name__ == "__main__":
    tests = [
        test_window_is_last_clean_quarters,
        test_number_check_accepts_and_rejects,
        test_cost_options,
        test_salary_fallback_and_median,
        test_metrics_for_all_stub_companies,
        test_profiles_cap,
        test_template_uses_only_inputs,
        test_prompt_lists_all_numbers,
        test_generate_card_with_fake_llm,
        test_parse_llm_rules,
    ]
    for t in tests:
        t()
        print(f"OK  {t.__name__}")
    print(f"Alle {len(tests)} testfuncties geslaagd.")
