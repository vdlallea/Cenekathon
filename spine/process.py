"""Slice A · Data spine.

Leest de ruwe Parquet-bestanden, maakt een steekproef van 20k, stript HTML,
telt vacatures per company_raw en schrijft spine.parquet + companies.parquet
volgens het contract in SPEC.md.

Gebruik (op de server, vanuit de root van je clone):
    python spine/process.py

Paden: standaard ~/data (= /home/team6/data op de server). Overschrijven met
    CENEK_DATA=/data python spine/process.py
"""

from __future__ import annotations

import html
import os
import re
import sys
import unicodedata
from collections import Counter
from pathlib import Path

import pandas as pd
from rapidfuzz import fuzz, process

DATA = Path(os.environ.get("CENEK_DATA", Path.home() / "data"))
RAW = DATA / "raw"
WORK = DATA / "work"

SEED = 42
SAMPLE_N = 20_000
DEDUP_DAYS = 30
RAW_COLS = ["vacancy_id", "title", "description", "company", "date_posted", "country", "city"]

# ---------------------------------------------------------------- HTML
TAG_RE = re.compile(r"</?[a-zA-Z][^>]{0,300}>")
WS_RE = re.compile(r"\s+")


def strip_html(value) -> str:
    if not isinstance(value, str):
        return ""
    value = TAG_RE.sub(" ", value)
    value = html.unescape(value)
    return WS_RE.sub(" ", value).strip()


# ---------------------------------------------------------------- bedrijfsnamen
# Juridische vormen en landnamen die weg mogen (groepsniveau).
LEGAL_RE = re.compile(
    r"\b(?:n v|nv|b v|bv|s a|sa|ltd|limited|plc|ag|gmbh|group|groep|holding|holdings|bank|banking|inc|"
    r"belgie|belgium|belgique|nederland|netherlands|uk|united kingdom|great britain)\b"
)
# Eigen werving van een groep ("NN Careers", "Natwest Careers", "JPMC Candidate Experience page")
# hoort bij de groep zelf, niet bij een apart bedrijf. Geen tussenpersoon.
OWN_CAREERS_RE = re.compile(
    r"\b(?:external |cws )?careers?\b(?: site)?|\bcandidate experience page\b"
)

# Handmatige aliaslijst voor de grote groepen. Uitbreiden na de top-50-handcheck.
# Ruwe namen per groep (groepsniveau). Sleutels worden door dezelfde normalisatie gehaald
# als de data, dus schrijf ze gewoon zoals ze gepost worden. Uitbreiden na de top-50-handcheck.
CANONICAL = {
    "ing": ["ING", "ING Netherlands", "ING Belgium", "ING Bank N.V.", "ING Bank"],
    "abn-amro": ["ABN AMRO", "ABN AMRO Bank N.V.", "ABN Amro", "ABN"],
    "rabobank": ["Rabobank", "Rabo Bank"],
    "kbc": ["KBC"],
    "belfius": ["Belfius", "BELFIUS BANK"],
    "bnp-paribas-fortis": ["BNP Paribas Fortis", "Fortis"],
    "bnp-paribas": ["BNP Paribas"],
    "lloyds": ["Lloyds", "Lloyds Banking Group", "Lloyds Bank"],
    "natwest": ["NatWest", "NatWest Group", "National Westminster"],
    "barclays": ["Barclays", "Barclays Bank PLC"],
    "hsbc": ["HSBC", "HSBC UK", "HSBC Bank"],
    "santander": ["Santander", "Santander UK", "Banco Santander"],
    "nationwide": ["Nationwide", "Nationwide Building Society"],
    "bank-of-america": ["Bank of America", "Bank of America Merrill Lynch"],
    "citi": ["Citi", "Citigroup", "Citigroup Inc.", "Citibank"],
    "jpmorgan-chase": ["JPMorgan Chase & Co.", "JPMorgan Chase", "JPMorganChase", "J.P. Morgan", "JP Morgan", "JPMC"],
    "allianz": ["Allianz", "Allianz Partners"],
    "peoples-partnership": ["People's Partnership", "Peoples Partnership"],
    "deutsche-bank": ["Deutsche Bank", "Deutsche Bank AG"],
    "wtw": ["WTW", "Willis Towers Watson"],
    "axa": ["AXA", "AXA UK", "AXA Partners"],
    "m-and-g": ["M&G", "M&G plc"],
    "triodos": ["Triodos", "Triodos Bank"],
    "aegon": ["AEGON"],
}

# Tussenpersonen: recruiters en jobsites die voor een ander posten.
AGENCY_NAME_RE = re.compile(
    r"recruit|staffing|uitzend|detachering|executive search|headhunt|"
    r"talent (?:partners|solutions|acquisition)|"
    r"\b(?:hays|michael page|robert walters|randstad|adecco|robert half|manpower|brunel|"
    r"tempo.?team|page personnel|reed|hudson|harvey nash|pertemps|morgan mc ?kinley|"
    r"badenoch|kelly services|computer futures|"
    r"youngcapital|young capital|veldsink|joof|"
    r"stepstone|efinancialcareers|totaljobs|cv-?library|indeed|jobserve|"
    r"studentjob|talent ?& ?pro|asa talent|start people|konvert interim|xtra interim|"
    r"talent link|city job offers|bebee|whatjobs|itzu jobs|jobs for humanity|"
    r"lgbt great careers|career wallet|nexus jobs|alexander mann|proactive appointments|"
    r"mw appointments|youconnect|i3 resourcing)\b|jobboard|job board",
    re.IGNORECASE,
)
AGENCY_TEXT_RE = re.compile(r"on behalf of (?:our|a|an|one of our) client", re.IGNORECASE)


def normalize_company(raw: str) -> str:
    s = unicodedata.normalize("NFKD", str(raw)).encode("ascii", "ignore").decode().lower()
    s = s.replace("&", " and ")
    s = re.sub(r"[^a-z0-9]+", " ", s)
    s = OWN_CAREERS_RE.sub(" ", s)
    s = LEGAL_RE.sub(" ", s)
    return WS_RE.sub(" ", s).strip()


# Genormaliseerde alias -> company_id. Zelfde normalisatie als de data, dus de sleutels passen.
ALIAS_TO_ID = {
    normalize_company(alias): cid for cid, aliases in CANONICAL.items() for alias in aliases
}


def resolve_company(norm: str) -> str:
    if not norm:
        return "onbekend"
    if norm in ALIAS_TO_ID:
        return ALIAS_TO_ID[norm]
    if len(norm) >= 5:
        hit = process.extractOne(norm, ALIAS_TO_ID.keys(), scorer=fuzz.ratio, score_cutoff=92)
        if hit:
            return ALIAS_TO_ID[hit[0]]
    return norm.replace(" ", "-")


# ---------------------------------------------------------------- taal
LANG_STOP = {
    "en": {"the", "and", "with", "you", "will", "our", "are", "for", "of", "to"},
    "nl": {"en", "het", "voor", "van", "met", "wij", "je", "een", "bij", "zijn"},
    "fr": {"le", "la", "et", "pour", "avec", "nous", "vous", "des", "dans", "les"},
    "de": {"und", "der", "die", "mit", "wir", "sie", "fur", "ein", "bei", "sind"},
}
WORD_RE = re.compile(r"[a-zà-ÿ]+")


def detect_lang(text: str) -> str:
    counts = Counter(WORD_RE.findall(text[:800].lower()))
    scores = {lang: sum(counts[w] for w in stop) for lang, stop in LANG_STOP.items()}
    best = max(scores, key=scores.get)
    return best if scores[best] >= 3 else "other"


# ---------------------------------------------------------------- stappen
def load_raw() -> pd.DataFrame:
    files = sorted(RAW.glob("**/*.parquet"))
    if not files:
        sys.exit(f"Geen parquet-bestanden gevonden in {RAW}")
    print(f"{len(files)} bestand(en) gelezen uit {RAW}")
    frames = [pd.read_parquet(f, columns=RAW_COLS) for f in files]
    raw = pd.concat(frames, ignore_index=True)
    raw = raw.rename(columns={"company": "company_raw", "description": "description_raw"})
    print(f"Ruwe rijen: {len(raw):,}")
    return raw


def print_company_counts(raw: pd.DataFrame) -> None:
    counts = raw["company_raw"].fillna("<leeg>").value_counts()
    print(f"\nVacatures per company_raw ({len(counts):,} unieke waarden), top 50:")
    print(counts.head(50).to_string())
    print()


def dedup(df: pd.DataFrame) -> pd.DataFrame:
    """Zelfde titel + bedrijf + eerste 200 tekens binnen 30 dagen na een behouden rij -> weg."""
    df = df.sort_values(["_key", "date_posted"], kind="stable")
    dup_rows = df[df.duplicated("_key", keep=False)]
    drop = []
    for _, grp in dup_rows.groupby("_key", sort=False):
        last = None
        for idx, day in zip(grp.index, grp["date_posted"]):
            if last is not None and (day - last).days <= DEDUP_DAYS:
                drop.append(idx)
            else:
                last = day
    print(f"Duplicaten verwijderd: {len(drop):,}")
    return df.drop(index=drop).drop(columns="_key")


def build_spine(raw: pd.DataFrame) -> pd.DataFrame:
    df = raw.copy()
    df["text"] = df["description_raw"].map(strip_html)
    df["title"] = df["title"].fillna("").astype(str).str.strip()
    df["company_raw"] = df["company_raw"].fillna("").astype(str)

    df["date_posted"] = pd.to_datetime(df["date_posted"], errors="coerce", utc=True).dt.tz_convert(None)
    no_date = df["date_posted"].isna().sum()
    df = df[df["date_posted"].notna()].copy()
    print(f"Rijen zonder datum weggelaten: {no_date:,}")

    df["country"] = (
        df["country"].fillna("").astype(str).str.strip().str.upper()
        .replace({"UK": "GB", "UNITED KINGDOM": "GB", "ENGLAND": "GB", "SCOTLAND": "GB",
                  "WALES": "GB", "BELGIUM": "BE", "NETHERLANDS": "NL", "LUXEMBOURG": "LU"})
    )
    odd = df.loc[~df["country"].isin(["BE", "NL", "LU", "GB"]), "country"].value_counts()
    if len(odd):
        print(f"Landen buiten BE/NL/LU/GB (blijven staan, bespreken met team):\n{odd.head(10).to_string()}")

    df["_key"] = (
        df["title"].str.lower().str.replace(WS_RE, " ", regex=True)
        + "|" + df["company_raw"].str.lower()
        + "|" + df["text"].str[:200].str.lower()
    )
    df = dedup(df)

    norm = df["company_raw"].map(normalize_company)
    unique_norm = norm.unique()
    mapping = {n: resolve_company(n) for n in unique_norm}
    df["company_id"] = norm.map(mapping)

    agency_name = df["company_raw"].str.contains(AGENCY_NAME_RE)
    agency_text = df["text"].str.contains(AGENCY_TEXT_RE)
    df["is_agency"] = (agency_name | agency_text).astype(bool)
    print(f"Tussenpersonen: {df['is_agency'].mean():.1%} van de vacatures "
          f"(op naam {agency_name.mean():.1%}, op tekst {agency_text.mean():.1%})")

    df["lang"] = df["text"].map(detect_lang)
    df["quarter"] = df["date_posted"].dt.year.astype(str) + "Q" + df["date_posted"].dt.quarter.astype(str)
    df["date_posted"] = df["date_posted"].dt.date

    spine = df[["vacancy_id", "company_raw", "company_id", "is_agency", "country", "city",
                "date_posted", "quarter", "lang", "title", "text"]].reset_index(drop=True)
    spine["vacancy_id"] = spine["vacancy_id"].astype(str)
    spine["city"] = spine["city"].fillna("").astype(str)
    return spine


def build_companies(spine: pd.DataFrame) -> pd.DataFrame:
    g = spine.groupby("company_id")
    companies = pd.DataFrame({
        "company_name": g["company_raw"].agg(lambda s: s.value_counts().index[0]),
        "is_agency": g["is_agency"].mean() > 0.5,
        "main_country": g["country"].agg(lambda s: s.value_counts().index[0]),
        "n_postings": g.size(),
    }).reset_index()
    return companies.sort_values("n_postings", ascending=False).reset_index(drop=True)


def main() -> None:
    WORK.mkdir(parents=True, exist_ok=True)

    raw = load_raw()
    print_company_counts(raw)

    raw["description_raw"] = raw["description_raw"].fillna("")
    raw["text"] = raw["description_raw"].map(strip_html)
    sample = raw.sample(n=min(SAMPLE_N, len(raw)), random_state=SEED)
    sample_path = WORK / "sample_20k.parquet"
    sample.drop(columns="description_raw").to_parquet(sample_path, index=False)
    print(f"Steekproef ({len(sample):,} rijen, seed {SEED}) -> {sample_path}")

    spine = build_spine(raw)
    spine_path = WORK / "spine.parquet"
    spine.to_parquet(spine_path, index=False)
    print(f"\nspine.parquet: {len(spine):,} rijen -> {spine_path}")

    companies = build_companies(spine)
    companies_path = WORK / "companies.parquet"
    companies.to_parquet(companies_path, index=False)
    print(f"companies.parquet: {len(companies):,} bedrijven -> {companies_path}")

    print("\nTop 50 company_id (voor handcheck):")
    print(companies.head(50)[["company_id", "company_name", "is_agency", "n_postings"]].to_string(index=False))
    print("\nTaal:", spine["lang"].value_counts(normalize=True).round(3).to_dict())


if __name__ == "__main__":
    main()
