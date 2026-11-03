"""AI Talent Radar – Streamlit-app (slice D).

Leest alleen kleine eindbestanden uit data/final/. Als een bestand ontbreekt,
valt de app terug op nepdata in app/stubs/ en toont een banner.
Geen live Claude-calls, geen netwerk, geen .env.

Draaien: streamlit run app/main.py
"""

import json
import sys
from pathlib import Path

import altair as alt
import pandas as pd
import streamlit as st

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from common import paths  # noqa: E402

GAP_NOTE = "gat in de dataverzameling (jan–jun 2026)"
TYPE_LABELS = {"share_builder": "Bouwer", "share_user": "Gebruiker", "share_governor": "Bewaker"}


# ---------- laden ----------

def _pick(final: Path, stub: Path) -> tuple[Path, bool]:
    """Geef het echte bestand als het bestaat, anders de stub. Tweede waarde: is het een stub?"""
    if final.exists():
        return final, False
    return stub, True


@st.cache_data
def load_tables() -> tuple[pd.DataFrame, pd.DataFrame, bool]:
    cq_path, cq_stub = _pick(paths.COMPANY_QUARTER, paths.STUB_COMPANY_QUARTER)
    peers_path, peers_stub = _pick(paths.PEERS, paths.STUB_PEERS)
    cq = pd.read_parquet(cq_path)
    peers = pd.read_parquet(peers_path)
    return cq, peers, cq_stub or peers_stub


@st.cache_data
def load_card(company_id: str) -> tuple[dict | None, bool]:
    final = paths.CARDS_DIR / f"{company_id}.json"
    stub = paths.STUB_CARDS_DIR / f"{company_id}.json"
    card_path, is_stub = _pick(final, stub)
    if not card_path.exists():
        return None, True
    with open(card_path, encoding="utf-8") as f:
        return json.load(f), is_stub


# ---------- berekeningen ----------

def weighted_share(df: pd.DataFrame, col: str) -> pd.Series:
    """Per kwartaal: aandeel gewogen op n_postings. Gebruikt voor bank én peer-gemiddelde."""
    g = df.assign(_w=df[col] * df["n_postings"]).groupby("quarter")
    return g["_w"].sum() / g["n_postings"].sum()


def gap_band(quarters: list[str]) -> alt.Chart | None:
    gap = [q for q in quarters if q.startswith("2026Q1") or q.startswith("2026Q2")]
    if not gap:
        return None
    return alt.Chart(pd.DataFrame({"quarter": gap})).mark_rect(color="#999", opacity=0.15).encode(
        x="quarter:N", tooltip=alt.value(GAP_NOTE)
    )


# ---------- app ----------

st.set_page_config(page_title="AI Talent Radar", layout="wide")
st.title("AI Talent Radar")

cq, peers_df, any_stub = load_tables()

if any_stub:
    st.warning("STUB-DATA: deze cijfers zijn verzonnen en dienen alleen om de app te testen.")

companies = sorted(cq["company_id"].unique())
default_idx = companies.index("kbc") if "kbc" in companies else 0
company = st.selectbox("Kies een bank", companies, index=default_idx)

peer_ids = (
    peers_df[(peers_df["company_id"] == company) & (peers_df["rank"] <= 5)]
    .sort_values("rank")["peer_id"]
    .tolist()
)
bank_cq = cq[cq["company_id"] == company]
peer_cq = cq[cq["company_id"].isin(peer_ids)]

# 1. Talentconcurrenten
st.header("1. Talentconcurrenten")
st.caption("De 5 banken met het meest gelijkaardige vacatureprofiel (cosine-similariteit).")
peer_table = (
    peers_df[(peers_df["company_id"] == company) & (peers_df["rank"] <= 5)]
    .sort_values("rank")[["rank", "peer_id", "similarity"]]
    .rename(columns={"peer_id": "concurrent", "similarity": "gelijkenis"})
)
st.dataframe(peer_table, hide_index=True, width="stretch")

# 2. AI-aandeel over de tijd
st.header("2. AI-aandeel over de tijd")
st.caption("Aandeel vacatures met een AI-skill per kwartaal. Concurrenten: gewogen gemiddelde van de top-5.")
bank_share = weighted_share(bank_cq, "share_ai").rename("bank")
peer_share = weighted_share(peer_cq, "share_ai").rename("concurrenten")
n_bank = bank_cq.groupby("quarter")["n_postings"].sum().rename("n_bank")
n_peer = peer_cq.groupby("quarter")["n_postings"].sum().rename("n_concurrenten")
share_df = pd.concat([bank_share, peer_share, n_bank, n_peer], axis=1).reset_index().rename(columns={"index": "quarter"})
share_df = share_df.sort_values("quarter")
quarters = share_df["quarter"].tolist()

long = share_df.melt(id_vars=["quarter"], value_vars=["bank", "concurrenten"], var_name="reeks", value_name="aandeel")
long["n"] = long["quarter"].map(n_bank).where(long["reeks"] == "bank", long["quarter"].map(n_peer))
lines = alt.Chart(long).mark_line(point=True).encode(
    x=alt.X("quarter:N", sort=quarters, title="kwartaal"),
    y=alt.Y("aandeel:Q", axis=alt.Axis(format="%"), title="aandeel AI-vacatures"),
    color="reeks:N",
    tooltip=["quarter", "reeks", alt.Tooltip("aandeel:Q", format=".1%"), alt.Tooltip("n:Q", title="n (vacatures)", format=",")],
)
band = gap_band(quarters)
st.altair_chart((band + lines) if band is not None else lines, width="stretch")

st.dataframe(
    share_df.assign(
        aandeel_bank=share_df["bank"].map(lambda v: f"{v:.1%}"),
        aandeel_concurrenten=share_df["concurrenten"].map(lambda v: f"{v:.1%}"),
        markering=share_df["quarter"].map(lambda q: GAP_NOTE if q in ("2026Q1", "2026Q2") else ""),
    )[["quarter", "aandeel_bank", "n_bank", "aandeel_concurrenten", "n_concurrenten", "markering"]],
    hide_index=True,
    width="stretch",
)

# 3. AI-mix
st.header("3. AI-mix")
st.caption("Verdeling bouwers / gebruikers / bewakers over de periode zonder het gat (2026Q1–Q2). Gewogen op n.")
clean_bank = bank_cq[~bank_cq["coverage_flag"]]
clean_peer = peer_cq[~peer_cq["coverage_flag"]]
n_mix_bank = int(clean_bank["n_postings"].sum())
n_mix_peer = int(clean_peer["n_postings"].sum())
mix_rows = []
for col, label in TYPE_LABELS.items():
    mix_rows.append({
        "type": label,
        "bank": weighted_share(clean_bank, col).mean(),
        "concurrenten": weighted_share(clean_peer, col).mean(),
    })
mix_df = pd.DataFrame(mix_rows)
mix_long = mix_df.melt(id_vars=["type"], var_name="reeks", value_name="aandeel")
mix_long["n"] = mix_long["reeks"].map({"bank": n_mix_bank, "concurrenten": n_mix_peer})
mix_chart = alt.Chart(mix_long).mark_bar().encode(
    x=alt.X("type:N", title=None),
    xOffset="reeks:N",
    y=alt.Y("aandeel:Q", axis=alt.Axis(format="%"), title="aandeel van alle vacatures"),
    color="reeks:N",
    tooltip=["type", "reeks", alt.Tooltip("aandeel:Q", format=".2%"), alt.Tooltip("n:Q", title="n (vacatures)", format=",")],
)
st.altair_chart(mix_chart, width="stretch")
st.dataframe(
    mix_df.assign(
        aandeel_bank=mix_df["bank"].map(lambda v: f"{v:.2%}"),
        aandeel_concurrenten=mix_df["concurrenten"].map(lambda v: f"{v:.2%}"),
        n_bank=n_mix_bank,
        n_concurrenten=n_mix_peer,
    )[["type", "aandeel_bank", "n_bank", "aandeel_concurrenten", "n_concurrenten"]],
    hide_index=True,
    width="stretch",
)
st.caption(
    "Elk type-aandeel is een deel van alle vacatures in die groep; daarom is de n per groep gelijk voor de drie types."
)

# 4. Adviesblok
st.header("4. Advies")
card, card_is_stub = load_card(company)
if card is None:
    st.info(f"Nog geen advies voor {company}. Wordt vooraf berekend (slice D).")
else:
    if card_is_stub:
        st.caption("Stub-advies: getallen zijn verzonnen.")
    st.subheader(card["headline"])
    for action in card.get("actions", [])[:3]:
        st.markdown(f"- **{action['advice']}** — kost €{action['cost_eur']:,.0f}")
    ev = card.get("evidence", {})
    if ev:
        st.caption(
            f"Bank AI-aandeel: {ev.get('share_ai', 0):.1%} · "
            f"concurrenten: {ev.get('peer_share_ai', 0):.1%} · "
            f"n: {ev.get('n', 0):,}"
        )
