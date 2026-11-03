"""Expliciete aannames van slice D (zie CLAUDE.md: geen verzonnen cijfers).

Elke constante hieronder is een bewuste keuze en geen gemeten waarde.
"""

# Omrekening van dag- en uurtarieven naar jaarsalaris (SPEC.md, contract salaries.parquet).
DAYS_PER_YEAR = 220
HOURS_PER_YEAR = 1950

# Een bedrag zonder eenheid (bv. "£55,000") wordt als jaarsalaris gelezen,
# maar alleen vanaf deze grens. Lager (bv. "£300") is te onduidelijk en wordt overgeslagen.
MIN_UNITLESS_ANNUAL_GBP = 10_000
