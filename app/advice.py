"""Adviesblok per bedrijf (slice D, SPEC.md: contract cards/<company_id>.json).

Stap 1: getallen per bedrijf uit company_quarter, peers en salaries (pandas, geen LLM).
Stap 2: kost van aanwerven tegenover omscholen (assumptions.py).
Stap 3: één Haiku-call per bedrijf die alleen die getallen krijgt en een headline en acties
        teruggeeft. Python controleert of elk getal in de output in de invoer voorkomt en
        zet de kosten zelf. Bij een fout of onbekend getal valt het terug op een vaste template.

Draaien:
  python app/advice.py --dry-run                 prompt per bedrijf printen, geen API, geen log
  python app/advice.py --dry-run --company kbc   prompt van één bedrijf
  python app/advice.py --company kbc             één Haiku-call (vereist ANTHROPIC_API_KEY)
"""

import argparse
import csv
import json
import math
import os
import re
import sys
from datetime import datetime, timezone
from pathlib import Path

import pandas as pd

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from common import paths  # noqa: E402
from assumptions import ASSUMPTIONS  # noqa: E402

MODEL = "claude-haiku-5-5"
N_WINDOW = 4  # laatste N schone kwartalen (coverage_flag = false)
PEER_RANK_MAX = 5
TYPES = ["builder", "user", "governor"]  # kolommen share_builder, share_user, share_governor
TYPE_NAME = {"builder": "AI-bouwers", "user": "AI-gebruikers", "governor": "AI-bewakers"}
PROFILE_NAME = {"builder": "AI-bouwers", "user": "AI-gebruikers", "governor": "AI-governanceprofielen"}
OPTIONS = ("aanwerven", "omscholen")
SALARIES_FINAL = paths.FINAL_DIR / "salaries.parquet"  # lokaal: nog niet in common/paths.py
SALARIES_STUB = paths.STUB_DIR / "salaries.parquet"


class NoData(Exception):
    """Bedrijf kan niet berekend worden (geen rijen, geen concurrenten)."""


def cfg(name: str):
    """Waarde uit assumptions.py."""
    return ASSUMPTIONS[name]["waarde"]


# ---------- inladen ----------

def load_inputs(use_stubs: bool = False):
    """company_quarter, peers en salaries. Salaries mag ontbreken (dan geldt de aanname)."""
    if use_stubs:
        cq_path, peers_path, sal_path = paths.STUB_COMPANY_QUARTER, paths.STUB_PEERS, SALARIES_STUB
    else:
        cq_path, peers_path, sal_path = paths.COMPANY_QUARTER, paths.PEERS, SALARIES_FINAL
    for p in (cq_path, peers_path):
        if not p.exists():
            raise FileNotFoundError(f"ontbreekt: {p}")
    cq = pd.read_parquet(cq_path)
    peers = pd.read_parquet(peers_path)
    salaries = pd.read_parquet(sal_path) if sal_path.exists() else None
    return cq, peers, salaries


def window_quarters(cq: pd.DataFrame) -> list[str]:
    """Laatste N_WINDOW schone kwartalen. Gelijk voor alle bedrijven, zodat ze eerlijk vergeleken worden."""
    clean = cq.loc[~cq["coverage_flag"].astype(bool), "quarter"].drop_duplicates()
    return sorted(clean)[-N_WINDOW:]


# ---------- stap 1: getallen ----------

def _share(df: pd.DataFrame, col: str) -> float:
    """Aandeel gewogen op n_postings (zelfde methode als app/main.py)."""
    return float((df[col] * df["n_postings"]).sum() / df["n_postings"].sum())


def salary_basis(salaries: pd.DataFrame | None) -> tuple[float, str, int]:
    """Jaarsalaris in EUR: mediaan van salary_min (GBP) omgerekend, of de aanname bij te weinig data."""
    n = 0 if salaries is None else len(salaries)
    if n < cfg("MIN_SALARIES_FOR_MEDIAN"):
        return float(cfg("FALLBACK_SALARY_EUR")), "aanname", n
    return float(salaries["salary_min"].median()) * cfg("GBP_TO_EUR"), "mediaan", n


def compute_metrics(company_id: str, cq: pd.DataFrame, peers: pd.DataFrame,
                    salaries: pd.DataFrame | None, quarters: list[str]) -> dict:
    """Ongeveer 20 getallen voor één bedrijf. Gooit NoData als het bedrijf niet vergelijkbaar is.

    Concurrenten worden samengevoegd (gewogen op n_postings), niet per concurrent gemiddeld.
    Profielen: exacte oplossing van (c + x) / (n + x) = p, met c = b·n: x = (p − b)·n / (1 − p),
    waarbij b het bankaandeel, p het concurrentaandeel en n het totaal van de bank is.
    """
    if not quarters:
        raise NoData("geen schone kwartalen")
    win = cq[cq["quarter"].isin(quarters)]
    bank = win[win["company_id"] == company_id]
    if bank.empty or bank["n_postings"].sum() == 0:
        raise NoData("geen vacatures in het venster")
    peer_ids = peers.loc[(peers["company_id"] == company_id) & (peers["rank"] <= PEER_RANK_MAX), "peer_id"].tolist()
    peer = win[win["company_id"].isin(peer_ids)]
    if peer.empty:
        raise NoData("geen concurrenten met data in het venster")

    n_bank = int(bank["n_postings"].sum())
    m = {
        "company_id": company_id,
        "n_quarters": len(quarters),
        "n_bank": n_bank,
        "n_peers": int(peer["n_postings"].sum()),
        "n_peer_companies": int(peer["company_id"].nunique()),
        "share_ai_bank": _share(bank, "share_ai"),
        "share_ai_peer": _share(peer, "share_ai"),
    }
    gaps = {}
    for t in TYPES:
        b, p = _share(bank, f"share_{t}"), _share(peer, f"share_{t}")
        gap = p - b  # positief = achterstand
        gaps[t] = gap
        m[f"share_{t}_bank"] = b
        m[f"share_{t}_peer"] = p
        m[f"achterstand_{t}"] = gap
        m[f"ratio_{t}"] = (p / b) if b > 0 else None

    top = max(TYPES, key=lambda t: gaps[t])
    if gaps[top] <= 0:
        m["grootste_type"] = None
        m["achterstand_grootste"] = 0.0
        m["profielen_per_kwartaal"] = 0
    else:
        p_top = m[f"share_{top}_peer"]
        needed = gaps[top] * n_bank / max(1.0 - p_top, 1e-9)
        per_q = math.ceil(needed / len(quarters))
        m["grootste_type"] = top
        m["achterstand_grootste"] = gaps[top]
        m["profielen_per_kwartaal"] = min(per_q, int(cfg("MAX_PROFILES_PER_QUARTER")))

    m["salaris_eur"], m["salaris_bron"], m["n_salarissen"] = salary_basis(salaries)
    return m


# ---------- stap 2: kosten ----------

def cost_options(profielen: int, salaris_eur: float) -> dict:
    """Kost per kwartaal in EUR. Wervingskost is een percentage van het jaarsalaris; omscholen is een vast bedrag."""
    return {
        "aanwerven": round(profielen * salaris_eur * cfg("RECRUIT_COST_PCT")),
        "omscholen": round(profielen * cfg("TRAINING_COST_EUR")),
    }


# ---------- opmaak en getallen ----------

def fmt_pct(x: float) -> str:
    """Fractie als procent met 1 decimaal, bv. 0.0612 -> '6.1'."""
    return f"{x * 100:.1f}"


def fmt_ratio(x: float) -> str:
    return f"{x:.1f}"


NUM_RE = re.compile(r"(?<![\w.,])\d+(?:[.,]\d+)*(?!\w)")
THOUSANDS_RE = re.compile(r"\d{1,3}(?:[.,]\d{3})+")


def _to_float(token: str) -> float:
    """'1.840' en '450.000' zijn duizendtallen; '3,5' en '3.0' zijn decimalen."""
    if THOUSANDS_RE.fullmatch(token):
        return float(re.sub(r"[.,]", "", token))
    return float(token.replace(",", "."))


def number_items(m: dict, costs: dict) -> list[tuple[str, str]]:
    """(label, weergave) voor elk getal dat naar Haiku gaat. De weergave is ook wat in de output mag voorkomen."""
    items = [
        ("kwartalen in venster (aantal)", str(m["n_quarters"])),
        ("vacatures bank in venster (n)", str(m["n_bank"])),
        ("vacatures concurrenten in venster (n)", str(m["n_peers"])),
        ("aandeel AI-vacatures bank (%)", fmt_pct(m["share_ai_bank"])),
        ("aandeel AI-vacatures concurrenten (%)", fmt_pct(m["share_ai_peer"])),
    ]
    for t in TYPES:
        gap = m[f"achterstand_{t}"]
        # Geen negatieve getallen: een voorsprong wordt een positief getal met het woord "voorsprong".
        # Zo kan het model het teken niet verliezen en de controle niet omzeilen.
        gap_label = "achterstand" if gap > 0 else "voorsprong"
        items += [
            (f"aandeel {TYPE_NAME[t]} bank (%)", fmt_pct(m[f"share_{t}_bank"])),
            (f"aandeel {TYPE_NAME[t]} concurrenten (%)", fmt_pct(m[f"share_{t}_peer"])),
            (f"{gap_label} {TYPE_NAME[t]} (procentpunt)", fmt_pct(abs(gap))),
        ]
        if m[f"ratio_{t}"] is not None:
            items.append((f"concurrenten t.o.v. bank, {TYPE_NAME[t]} (×)", fmt_ratio(m[f"ratio_{t}"])))
    items += [
        ("profielen per kwartaal nodig (aantal)", str(m["profielen_per_kwartaal"])),
        ("kost aanwerven per kwartaal (EUR)", str(costs["aanwerven"])),
        ("kost omscholen per kwartaal (EUR)", str(costs["omscholen"])),
        ("salarisbasis profiel (EUR per jaar)", str(round(m["salaris_eur"]))),
    ]
    return items


def unknown_numbers(text: str, allowed: set[float]) -> list[str]:
    """Getallen in de tekst die niet in de invoer voorkomen."""
    bad = []
    for token in NUM_RE.findall(text):
        value = _to_float(token)
        if not any(abs(value - ok) < 1e-9 for ok in allowed):
            bad.append(token)
    return bad


# ---------- prompt en Haiku ----------

def build_prompt(company_id: str, m: dict, costs: dict) -> tuple[str, list[tuple[str, str]]]:
    items = number_items(m, costs)
    numbers = "\n".join(f"- {label}: {value}" for label, value in items)
    prompt = f"""Je schrijft een kort adviesblok voor de HR-strategieverantwoordelijke van bank {company_id.upper()} over AI-talent: loopt de bank achter op haar talentconcurrenten, en wat moet ze doen?

Regels (strikt):
- Gebruik ALLEEN de getallen uit de lijst hieronder, exact zoals ze staan, in cijfers.
- Verzin geen enkel getal: geen percentages, bedragen, aantallen of jaartallen die niet in de lijst staan.
- Noem geen kwartaalnamen (bv. 2025Q4).
- De grootste achterstand is: {TYPE_NAME[m["grootste_type"]]}. Het profiel is: {PROFILE_NAME[m["grootste_type"]]}.
- headline: één zin van maximaal 20 woorden. Noem de achterstand op {TYPE_NAME[m["grootste_type"]]} met het aandeel van de bank en het aandeel van de concurrenten. Gebruik maximaal twee getallen in de zin. Geen "dus" of advies in de headline.
- actions: precies 2 acties, één met "optie": "aanwerven" en één met "optie": "omscholen". Ze zijn ALTERNATIEVEN, geen optelling: schrijf dat niet als extra, maar als twee manieren om dezelfde achterstand te dichten. Elke actie noemt het aantal profielen per kwartaal en de optie, en gaat over {PROFILE_NAME[m["grootste_type"]]} en niet over andere profieltypes. Elke advice is één zin met maximaal twee getallen.
- Antwoord alleen met JSON, zonder tekst eromheen, in dit formaat:
{{"headline": "...", "actions": [{{"advice": "...", "optie": "aanwerven"}}]}}

Getallen:
{numbers}
"""
    return prompt, items


def parse_llm(raw: str) -> dict | None:
    """Geldige headline + 1 tot 3 acties met een bekende optie, anders None."""
    match = re.search(r"\{.*\}", raw, re.DOTALL)
    if not match:
        return None
    try:
        data = json.loads(match.group(0))
    except json.JSONDecodeError:
        return None
    headline, actions = data.get("headline"), data.get("actions")
    if not isinstance(headline, str) or not headline.strip():
        return None
    if not isinstance(actions, list) or not 1 <= len(actions) <= 3:
        return None
    for action in actions:
        if not isinstance(action, dict) or not isinstance(action.get("advice"), str):
            return None
        if action.get("optie") not in OPTIONS:
            return None
    return data


def log_usage(company_id: str, input_tokens: int, output_tokens: int) -> None:
    """Eén regel per API-call in logs/claude_usage.csv (kolommen gelijk aan SPEC: kostslide)."""
    paths.LOGS_DIR.mkdir(parents=True, exist_ok=True)
    new_file = not paths.USAGE_LOG.exists() or paths.USAGE_LOG.stat().st_size == 0
    with open(paths.USAGE_LOG, "a", newline="", encoding="utf-8") as f:
        writer = csv.writer(f)
        if new_file:
            writer.writerow(["timestamp", "company_id", "input_tokens", "output_tokens"])
        writer.writerow([datetime.now(timezone.utc).isoformat(timespec="seconds"),
                         company_id, input_tokens, output_tokens])


def call_haiku(prompt: str, company_id: str) -> str:
    """Eén call. De sleutel komt uit de omgeving; .env wordt nooit gelezen."""
    import anthropic  # pas hier, zodat --dry-run zonder het pakket werkt

    client = anthropic.Anthropic(api_key=os.environ["ANTHROPIC_API_KEY"])
    resp = client.messages.create(model=MODEL, max_tokens=2000, messages=[{"role": "user", "content": prompt}])
    log_usage(company_id, resp.usage.input_tokens, resp.usage.output_tokens)
    text = "".join(block.text for block in resp.content if getattr(block, "type", "") == "text")
    if not text.strip():
        # Geen tekst: laat zien waarom, zodat de oorzaak zichtbaar is.
        blocks = [getattr(block, "type", "?") for block in resp.content]
        raise ValueError(f"leeg antwoord, stop_reason={resp.stop_reason}, bloktypen={blocks}")
    return text


# ---------- kaarten ----------

def evidence(m: dict) -> dict:
    return {"share_ai": round(m["share_ai_bank"], 4), "peer_share_ai": round(m["share_ai_peer"], 4), "n": m["n_bank"]}


def template_card(m: dict, costs: dict) -> dict:
    """Vaste tekst met alleen berekende getallen. Gebruikt als de Haiku-output niet klopt."""
    name = m["company_id"].upper()
    top = m["grootste_type"]
    if top is None:
        headline = f"{name} loopt in de laatste schone kwartalen niet achter op de concurrenten in AI-vacatures"
        actions = []
    else:
        p = m["profielen_per_kwartaal"]
        headline = (f"{name} heeft {fmt_pct(m[f'share_{top}_bank'])}% {TYPE_NAME[top]} in de vacatures, "
                    f"concurrenten {fmt_pct(m[f'share_{top}_peer'])}%")
        actions = [
            {"advice": f"Werf {p} {PROFILE_NAME[top]} aan per kwartaal", "cost_eur": costs["aanwerven"]},
            {"advice": f"Schoolt {p} medewerkers per kwartaal om tot {PROFILE_NAME[top]}", "cost_eur": costs["omscholen"]},
        ]
    return {"company_id": m["company_id"], "headline": headline, "actions": actions, "evidence": evidence(m)}


def generate_card(m: dict, costs: dict, prompt: str, items: list[tuple[str, str]]) -> dict:
    """Haiku-call met controle. Elke afwijking geeft de template terug, met een melding."""
    allowed = {float(value) for _, value in items}
    company_id = m["company_id"]
    try:
        raw = call_haiku(prompt, company_id)
    except Exception as exc:  # netwerk- of API-fout: template, zodat de kaart er toch is
        print(f"  API-fout ({type(exc).__name__}): {exc}; template gebruikt")
        return template_card(m, costs)
    data = parse_llm(raw)
    if data is None:
        # Ruwe output tonen zodat je ziet wat het model stuurde (alleen getallen en tekst, geen dataset).
        print("  geen geldige JSON van het model: template gebruikt")
        print(f"  ruwe output (eerste 400 tekens): {raw[:400]!r}")
        return template_card(m, costs)
    texts = [data["headline"]] + [action["advice"] for action in data["actions"]]
    bad = [tok for text in texts for tok in unknown_numbers(text, allowed)]
    if bad:
        print(f"  getallen die niet in de invoer staan {bad}: template gebruikt")
        return template_card(m, costs)
    return {
        "company_id": company_id,
        "headline": data["headline"].strip(),
        "actions": [{"advice": action["advice"].strip(), "cost_eur": costs[action["optie"]]}
                    for action in data["actions"]],
        "evidence": evidence(m),
    }


def write_card(card: dict) -> Path:
    paths.CARDS_DIR.mkdir(parents=True, exist_ok=True)
    out = paths.CARDS_DIR / f"{card['company_id']}.json"
    with open(out, "w", encoding="utf-8") as f:
        json.dump(card, f, ensure_ascii=False, indent=2)
    return out


# ---------- CLI ----------

def process(company_id: str, cq, peers, salaries, quarters, dry_run: bool) -> None:
    try:
        m = compute_metrics(company_id, cq, peers, salaries, quarters)
    except NoData as exc:
        print(f"{company_id}: overgeslagen ({exc})")
        return
    costs = cost_options(m["profielen_per_kwartaal"], m["salaris_eur"])

    if m["grootste_type"] is None:
        # Geen achterstand: geen Haiku-call nodig, de template volstaat.
        if dry_run:
            print(f"{company_id}: geen achterstand, geen Haiku-call nodig")
            return
        card = template_card(m, costs)
    else:
        prompt, items = build_prompt(company_id, m, costs)
        if dry_run:
            print(f"===== {company_id} =====")
            print(prompt)
            print(f"(kosten aanwerven={costs['aanwerven']}, omscholen={costs['omscholen']}; "
                  f"salarisbron={m['salaris_bron']})")
            return
        card = generate_card(m, costs, prompt, items)

    out = write_card(card)
    print(f"{company_id}: {card['headline']}  -> {out}")


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Adviesblok per bedrijf (Haiku, met controle op getallen).")
    parser.add_argument("--company", help="draai alleen dit company_id")
    parser.add_argument("--dry-run", action="store_true", help="print de prompt, zonder API-call en zonder logregel")
    args = parser.parse_args(argv)

    if not args.dry_run and "ANTHROPIC_API_KEY" not in os.environ:
        print("ANTHROPIC_API_KEY ontbreekt in de omgeving. Gebruik --dry-run om zonder API te testen.")
        return 1

    cq, peers, salaries = load_inputs()
    quarters = window_quarters(cq)
    if salaries is None:
        print("WAARSCHUWING: salaries.parquet ontbreekt; het salaris is overal de aanname.")
    print(f"Venster: {', '.join(quarters)}")

    companies = sorted(cq["company_id"].unique())
    if args.company:
        if args.company not in companies:
            print(f"Onbekend company_id: {args.company}")
            return 1
        companies = [args.company]
    for company_id in companies:
        process(company_id, cq, peers, salaries, quarters, args.dry_run)
    return 0


if __name__ == "__main__":
    sys.exit(main())
