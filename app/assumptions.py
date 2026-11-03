"""Expliciete aannames van slice D (zie CLAUDE.md: geen verzonnen cijfers).

Elke constante hieronder is een bewuste keuze en geen gemeten waarde.
"""

# Omrekening van dag- en uurtarieven naar jaarsalaris (SPEC.md, contract salaries.parquet).
DAYS_PER_YEAR = 220
HOURS_PER_YEAR = 1950

# Een bedrag zonder eenheid (bv. "£55,000") wordt als jaarsalaris gelezen,
# maar alleen vanaf deze grens. Lager (bv. "£300") is te onduidelijk en wordt overgeslagen.
MIN_UNITLESS_ANNUAL_GBP = 10_000

# Aannames voor de kostberekening (advice.py). Elke waarde is een bewuste keuze, geen meting.
# Wijzig de waarde hier; advice.py leest alleen deze dict.
ASSUMPTIONS = {
    # Wervingskost als deel van het jaarsalaris (recruiter-fee, advertentie, intern proces).
    "RECRUIT_COST_PCT": {"waarde": 0.20, "bron": "aanname"},
    # Opleidingskost per omgeschoolde persoon, in EUR.
    "TRAINING_COST_EUR": {"waarde": 4_000, "bron": "aanname"},
    # Gemiddeld jaarsalaris van een AI-governanceprofiel in EUR, als er geen salarisdata is.
    "FALLBACK_SALARY_EUR": {"waarde": 60_000, "bron": "aanname"},
    # Koers om UK-salarissen (GBP) om te rekenen naar EUR. Moet nagekeken worden.
    "GBP_TO_EUR": {"waarde": 1.20, "bron": "aanname"},
    # Realistische bovengrens: meer profielen per kwartaal werf je niet aan.
    "MAX_PROFILES_PER_QUARTER": {"waarde": 10, "bron": "aanname"},
    # Minimum aantal salarissen voor een betrouwbare mediaan; daaronder valt de kost terug op FALLBACK_SALARY_EUR.
    "MIN_SALARIES_FOR_MEDIAN": {"waarde": 30, "bron": "aanname"},
}
