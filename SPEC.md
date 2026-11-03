# CenEkathon – Teamplan AI Talent Radar

Nov 3, 2026 · @Owen

## In één minuut

We bouwen **AI Talent Radar**: een tool die één bank toont hoe snel ze naar AI beweegt tegenover haar échte talentconcurrenten, en wat ze moet doen.

**De zin die alles stuurt:** de HR-strategieverantwoordelijke van een bank gebruikt AI Talent Radar om te beslissen of ze AI-profielen moet aanwerven, mensen moet omscholen of AI-governance moet bijbouwen.

**Het demoverhaal (90 seconden):**

1. Kies een bank, bijvoorbeeld KBC.
2. De tool toont haar talentconcurrenten: banken die dezelfde profielen zoeken, berekend uit de vacatures zelf. Niet wie de bank zelf als concurrent ziet.
3. Per kwartaal zie je het aandeel AI-vacatures, opgesplitst in **bouwers**, **gebruikers** en **bewakers**, naast dat van de concurrenten.
4. Eén adviesblok met een getal: bijvoorbeeld "Je concurrenten werven 3× meer bewakers aan. Werf 5 AI-governanceprofielen aan of schoolt 15 risk-analisten om: kost €X tegenover €Y."

**Iedereen bouwt één stuk (slice) van begin tot eind.** De stukken praten met elkaar via vaste bestanden met vaste kolommen (sectie Contracten). Zolang je die afspraken volgt, kun je niets kapotmaken voor een ander.

## De case kort

**Opdracht van TechWolf:** AI verandert hoe bedrijven werken en wie ze aannemen. Help een bedrijf begrijpen waar het staat. Speelveld: financiële sector (Benelux en VK). De case is open; de harde eis is dat het eindigt in **concreet advies**, niet in een dashboard.

**Data:** 1.542.169 vacatures (jan 2021 tot sep 2026) van banken, verzekeraars en betaalbedrijven, plus recruiters en jobsites die voor hen posten. Kolommen: `vacancy_id`, `title`, `description`, `company` (zoals gepost), `date_posted`, `country`, `city`. Geen labels, geen skills, geen schone bedrijfsnamen. Ongeveer 75% is VK.

**Scoring (op 20):**

| Onderdeel | Punten | Wat de jury wil zien |
| --- | --- | --- |
| Waarde | 6 | Correct, concreet advies waar een klant voor betaalt |
| Kost en schaalbaarheid | 6 | LLM alleen waar het loont; werkt op 100× meer data |
| Creativiteit | 4 | Onverwacht inzicht, databron of aanpak |
| Pitch | 4 | Duidelijk verhaal, demo werkt, iedereen kan alles uitleggen |

**Inleveren:** repo (zip), architectuurslide, kostslide (tokens, euro's, euro per extra bedrijf, wat breekt bij 100×), pitch van 5 min + 5 min vragen. Live demo is een bonus.

**Middelen:** één gedeelde Claude-sleutel ($80, standaard Haiku 5.5), één GPU-server (A100 40 GB, 85 GB RAM, 12 cores), open modellen (e5, bge-m3, JobBERT-v3, Gemma 4) en open data (ESCO, GLEIF, AI-exposure per beroep). Synthetische *interne* data van de bank mag; interne data van concurrenten niet.

**Valkuilen die de jury zoekt:** de dip in jan–apr 2026 is een gat in de dataverzameling, geen minder aanwerving. Recruiters staan in de kolom `company`. Meerdere talen. Reposts en duplicaten. Werk daarom met **aandelen**, niet met absolute aantallen.

## Wat we bouwen

**Eén gebruiker, één vraag, één demopad.** Gebruiker: HR-strategieverantwoordelijke van één bank. Vraag: "Lopen wij voor of achter op AI tegenover onze echte talentconcurrenten, en wat doen we eraan?" Demopad: bank kiezen → concurrenten → AI-aandeel per type over de tijd → adviesblok.

**Het product toont per bank vier blokken:**

1. **Talentconcurrenten:** de 5 banken met het meest gelijkaardige vacatureprofiel, met een gelijkenisscore.
2. **AI-aandeel over de tijd:** % vacatures met een AI-skill per kwartaal, bank tegenover gemiddelde van de concurrenten.
3. **AI-mix:** verdeling bouwers / gebruikers / bewakers, bank tegenover concurrenten.
4. **Advies:** maximaal 3 acties, elk met een getal (aantal profielen, kost in euro).

### Definities (gebruik exact deze, ook in prompts en code)

| Begrip | Definitie |
| --- | --- |
| AI-vacature | De vacature *vraagt* een AI-skill als vereiste of taak. Boilerplate over het bedrijf ("wij zijn een AI-gedreven bank") telt niet. |
| Bouwer | Ontwikkelt, traint of zet AI/ML-modellen of -systemen in productie. Voorbeelden: ML engineer, data scientist die modellen bouwt, MLOps, AI/LLM engineer. |
| Gebruiker | Een niet-AI-functie waarvan verwacht wordt dat ze AI-tools gebruikt: Copilot, ChatGPT, "AI tools", prompting, automatisering met AI. |
| Bewaker | Bewaakt risico, compliance of ethiek van AI: AI-governance, responsible AI, EU AI Act, AI-audit. *Model risk* telt alleen als AI of ML expliciet vermeld wordt; klassieke kredietmodelvalidatie telt niet. |
| Geen | Geen AI-skill gevraagd. |
| Eén label per vacature | Bij twijfel geldt de volgorde bouwer > bewaker > gebruiker. |
| Bedrijf | De werkgever op **groepsniveau**: ING België + ING Nederland = ING. Beslissing: we vergelijken groepen. |
| Tussenpersoon | Recruiter of jobsite die voor een ander post (Hays, Michael Page, Robert Walters…). Krijgt `is_agency = true` en valt uit de vergelijking tussen bedrijven. |
| Talentconcurrent | Een bedrijf waarvan het gemiddelde embedding-profiel van al zijn vacatures het dichtst bij dat van de gekozen bank ligt (cosine-similariteit). |
| Kwartaal | Uit `date_posted`, notatie `2024Q3`. Rijen zonder datum (271) laten we vallen. Kwartalen in 2026Q1–Q2 krijgen een markering wegens het gat in de dataverzameling. |
| Aandeel | Aantal AI-vacatures / totaal aantal vacatures van dat bedrijf in dat kwartaal. Toon altijd de `n` ernaast. |

## Wat we niet doen

Wie iets van deze lijst wil bouwen, overlegt eerst met het hele team.

- Geen live scraping, geen gebruikersaccounts, geen mobiele app.
- Geen Claude over alle 1,5 miljoen vacatures. Claude labelt een steekproef en schrijft het eindadvies, verder niets.
- Geen eigen deep model trainen. Embeddings + logistische regressie volstaan.
- Geen live LLM-calls in de app: advies wordt vooraf berekend en opgeslagen.
- Geen klanten achterhalen achter recruiters (tussenpersonen worden gemarkeerd en weggelaten). Enkel als er tijd over is.
- Geen lead-lag-analyse (wie volgt wie). Enkel als er tijd over is.
- Geen Sonnet of Opus zonder overleg.

## Architectuur

Vijf stappen, waarvan er maar één echt intelligentie nodig heeft (het taggen). De rest is regels, SQL en embeddings op onze eigen GPU.

1. **Spine (A):** ruwe Parquet → ontdubbelen, HTML strippen, bedrijfsnaam normaliseren, tussenpersonen markeren → `spine.parquet`.
2. **Embeddings (C):** titel + eerste \~400 woorden van de beschrijving → vector per vacature, op de GPU → `embeddings.npy`.
3. **Taggen (B):** AI-woordenlijst als basislijn → Claude labelt een steekproef → klein model op de embeddings tagt de rest → `tags.parquet`.
4. **Aggregeren en concurrenten (C):** aandelen per bedrijf en kwartaal + gemiddelde vector per bedrijf → dichtstbijzijnde bedrijven → `company_quarter.parquet`, `peers.parquet`.
5. **Advies en app (D):** template + één Haiku-call per bedrijf over \~20 getallen → `cards/<company_id>.json` → Streamlit-app die alleen die kleine bestanden leest.

| Stap | Methode | Waarom |
| --- | --- | --- |
| Bedrijf normaliseren | Lowercase, rechtsvormen weg (N.V., Ltd, plc…), handmatige aliaslijst voor top-50, daarna fuzzy match (rapidfuzz) | Gratis, uitlegbaar; de jury vraagt welk deel we *niet* met AI bouwden |
| Tussenpersoon herkennen | Lijst van gekende recruiters + regex ("recruitment", "on behalf of our client") | Regel volstaat |
| AI-skill aanwezig | Basislijn: woordenlijst (machine learning, LLM, Copilot, generative AI…). Upgrade: logistische regressie op embeddings | Staat meestal letterlijk in de tekst; meten of het model beter doet |
| Bouwer / gebruiker / bewaker | Claude Haiku labelt \~1.500 vacatures → logistische regressie op embeddings voor de rest | Grote model leert het kleine; kost bijna niets per extra vacature |
| Embeddings | `intfloat/multilingual-e5-base` (meertalig) op de A100 | NL, FR en EN landen in dezelfde ruimte; ±1 uur voor alles |
| Concurrenten | Gemiddelde vector per bedrijf, cosine-similariteit, top-5 | Geen LLM nodig, deterministisch |
| Advies | Template + Haiku over \~20 getallen per bedrijf, vooraf berekend | LLM alleen waar een mens het leest |
| Salaris (voor kost) | Regex op UK-vacatures ("£55,000 - £65,000") | Expliciete info, geen model nodig |

**Waarom dit goed scoort op kost:** het enige Claude-verbruik is \~1.500 labels plus één call per bedrijf. Een extra bedrijf kost dus bijna niets. Bij 100× meer data groeit alleen de GPU-tijd voor embeddings.

## Taakverdeling

Vier slices, elk met één eigenaar en één eigen map in de repo. Je schrijft alleen in je eigen map en je eigen outputbestanden. Iedereen levert in het eerste halfuur een **stub**: een bestand met de juiste kolommen en nepwaarden, zodat niemand op een ander wacht.

| Slice | Eigenaar | Map | Schrijft | Leest |
| --- | --- | --- | --- | --- |
| A · Data spine | \_\_\_ | `spine/` | `spine.parquet`, `sample_20k.parquet`, `companies.parquet` | ruwe Parquet |
| B · Taggen | \_\_\_ | `tagging/` | `tags.parquet` | spine, embeddings |
| C · Embeddings, aandelen, concurrenten | \_\_\_ | `peers/` | `embeddings.npy`, `company_quarter.parquet`, `peers.parquet` | spine, tags, companies |
| D · Advies, app, pitch | \_\_\_ | `app/` | `cards/*.json`, `salaries.parquet`, de slides | alles hierboven |

### A · Data spine

- **Doel:** één schone tabel waar iedereen op bouwt, en een betrouwbare bedrijfsnaam.
- **Eerste 45 min:** data downloaden naar de server, `sample_20k.parquet` maken (willekeurig, seed 42), stub-`spine.parquet` pushen. Telling van vacatures per `company` delen met het team.
- **Daarna:** HTML strippen, ontdubbelen (zelfde titel + bedrijf + eerste 200 tekens beschrijving binnen 30 dagen), taal detecteren, bedrijfsnamen normaliseren naar groepen, tussenpersonen markeren.
- **Klaar als:** `spine.parquet` en `companies.parquet` op de volledige data staan, volgens het contract.
- **Evaluatie:** top-50 bedrijven met de hand nagekeken; % vacatures van tussenpersonen; aantal duplicaten verwijderd.
- **Juryvraag die jij beantwoordt:** "Welke naamvarianten en tussenpersonen vonden jullie, en wat deden jullie ermee?"

### B · Taggen

- **Doel:** per vacature: AI ja/nee en type (bouwer / gebruiker / bewaker / geen).
- **Eerste 45 min:** AI-woordenlijst opstellen en draaien op de sample (basislijn), stub-`tags.parquet` pushen, prompt voor Claude schrijven met de definities hierboven.
- **Daarna:** steekproef van \~1.500 vacatures, gespreid over land, taal en jaar, met extra gewicht op vacatures waar de woordenlijst iets vindt (AI is zeldzaam). Claude Haiku labelt. 100 labels met de hand controleren. Logistische regressie trainen op de embeddings van C. Toepassen op alles.
- **Klaar als:** `tags.parquet` op de volledige data staat, met een `confidence`-kolom.
- **Evaluatie:** aparte testset van 300 vacatures die nooit in training of prompt zit. Precision en recall voor AI ja/nee, F1 per type, per taal apart. Vergelijking met de woordenlijst.
- **Juryvraag:** "Waar komen jullie labels vandaan, en hoe ruizig zijn ze?"

### C · Embeddings, aandelen, concurrenten

- **Doel:** de embeddings voor iedereen, en de cijfers per bedrijf en kwartaal.
- **Eerste 45 min:** `multilingual-e5-base` laden op de GPU, embeddings op de sample draaien, stubs van `company_quarter.parquet` en `peers.parquet` pushen.
- **Daarna:** embeddings op alles (in tmux, ±1 uur). Aandelen per bedrijf en kwartaal berekenen. Vector per bedrijf, top-5 concurrenten (alleen bedrijven met ≥ 200 vacatures, geen tussenpersonen).
- **Klaar als:** beide tabellen op de volledige data staan.
- **Evaluatie:** komen gekende concurrenten bovendrijven (ING ↔ ABN AMRO ↔ Rabobank; KBC ↔ Belfius ↔ BNP Paribas Fortis)? Per land nagaan. Eén trend vergelijken met het nieuws.
- **Juryvraag:** "Hoe weten jullie dat de concurrentenlijst klopt?"

### D · Advies, app, pitch

- **Doel:** van tabellen naar een advies waar een bank voor betaalt, en het verhaal.
- **Eerste 45 min:** repo-skelet (mappen, `requirements.txt`, `common/paths.py`), Streamlit-app die de stubs leest en de vier blokken toont.
- **Daarna:** salarissen uit UK-vacatures halen (regex), kost berekenen (aanwerven tegenover omscholen), adviestemplate + Haiku-prompt, kaarten vooraf genereren. Architectuur- en kostslide, pitch, opname van de demo als back-up.
- **Klaar als:** de app werkt op een laptop zonder GPU, enkel met de kleine bestanden uit `data/final/`.
- **Evaluatie:** 10 kaarten nalezen met een vaste checklist (volgt het advies uit de getallen? geen verzonnen cijfers?). Kost per extra bedrijf, wat breekt bij 100×.
- **Juryvraag:** "Wat gebeurt er met 100× meer data morgen?"

**Iedereen kan elk deel uitleggen.** De jury stelt elke vraag aan een ander teamlid.

## Contracten

Dit is de belangrijkste sectie. Kolomnamen en types veranderen **alleen** na een bericht in de groep én een aanpassing van `SPEC.md` via een pull request. Paden staan op één plek: `common/paths.py`.

### Mappen

```
Repo (GitHub)                     Server (~ = /home/team6)
SPEC.md        ← dit plan         ~/data/raw/       ruwe Parquet (alleen A schrijft)
common/paths.py                   ~/data/work/      tussenbestanden (spine, tags, embeddings)
spine/    (A)                     ~/<naam>/Cenekathon/  ieders eigen clone
tagging/  (B)
peers/    (C)
app/      (D)
data/final/  kleine eindbestanden (< 20 MB), wél in git
```

### Bestanden

**`spine.parquet`** (A, in `~/data/work/`) — één rij per vacature na ontdubbelen

```
vacancy_id     str     zoals in de ruwe data
company_raw    str     zoals gepost
company_id     str     slug op groepsniveau, bv. "ing", "kbc", "abn-amro"
is_agency      bool    true = recruiter/jobsite
country        str     BE | NL | LU | GB
city           str
date_posted    date
quarter        str     "2024Q3"
lang           str     en | nl | fr | de | other
title          str
text           str     beschrijving zonder HTML
```

**`companies.parquet`** (A) — één rij per `company_id`: `company_id`, `company_name` (leesbaar), `is_agency`, `main_country`, `n_postings`.

**`embeddings.npy`** (C) — float32-matrix, rij *i* hoort bij `embeddings_ids.parquet` rij *i* (kolom `vacancy_id`). Nooit op rijvolgorde van de spine vertrouwen.

**`tags.parquet`** (B)

```
vacancy_id     str
has_ai         bool
ai_type        str     builder | user | governor | none
confidence     float   0–1
source         str     claude | model | keyword
```

**`company_quarter.parquet`** (C, eindversie in `data/final/`)

```
company_id, quarter, n_postings, share_ai, share_builder, share_user, share_governor, coverage_flag (bool)
```

**`peers.parquet`** (C, eindversie in `data/final/`): `company_id`, `peer_id`, `similarity`, `rank` (1–5).

**`salaries.parquet`** (D, in `data/final/` of `~/data/work/`): één rij per UK-vacature met een gevonden salaris. Kolommen: `vacancy_id` (str, zoals in spine), `company_id` (str, zoals in spine), `salary_min` (float, jaarsalaris in GBP; dag × 220, uur × 1950), `salary_max` (float, gelijk aan `salary_min` als er maar één bedrag staat), `currency` (str, "GBP"), `period` (str: year | day | hour, oorspronkelijke eenheid).

**`cards/<company_id>.json`** (D, in `data/final/`)

```
{
  "company_id": "kbc",
  "headline": "KBC werft 3× minder AI-bewakers aan dan haar concurrenten",
  "actions": [
    {"advice": "Werf 5 AI-governanceprofielen aan", "cost_eur": 450000},
    {"advice": "Schoolt 15 risk-analisten om", "cost_eur": 120000}
  ],
  "evidence": {"share_ai": 0.06, "peer_share_ai": 0.11, "n": 1840}
}
```

De getallen in dit voorbeeld zijn verzonnen; het is een stub.

## Werkafspraken

### Git

- Repo: [github.com/vdlallea/Cenekathon](https://github.com/vdlallea/Cenekathon). Werk op een eigen branch `naam/feature`, open een pull request, een teamgenoot reviewt. Nooit rechtstreeks op `main`.
- Je wijzigt alleen bestanden in je eigen map. `SPEC.md` en `common/paths.py` alleen via een PR die je in de groep aankondigt.
- Nooit in git: `.env`, ruwe data, `embeddings.npy`, alles in `~/data/`. Wel in git: kleine eindbestanden in `data/final/` (< 20 MB).
- Kleine PR's, vaak mergen: minstens elk uur. Een stub die end-to-end werkt is beter dan een perfect stuk dat om 18 uur binnenkomt.

### Server (team6, 35.200.118.210)

- Inloggen: `ssh team6@35.200.118.210`, wachtwoord in het GPU-document. Alleen via het wifi van de locatie of eduroam. Makkelijkst via VS Code: Remote-SSH → Connect to Host.
- **We delen één Linux-gebruiker.** Werk dus in je eigen map `~/<naam>/` met je eigen clone. Zet in je clone `git config user.name` en `user.email` **zonder** `--global`. Via VS Code Remote-SSH gebruikt git je eigen GitHub-login.
- Gedeelde data staat in `~/data/`. Alleen de eigenaar van een bestand schrijft het (zie Contracten).
- Eén gedeelde Python-omgeving `~/venv`, aangemaakt door A. Wie een pakket installeert, meldt dat in de groep en zet het in `requirements.txt`.
- **De server gaat om 20:30 uit.** Wat tegen dan niet in git staat, is weg.

### GPU (één A100, 40 GB, voor ons vieren)

- Lange jobs altijd in `tmux` (sessienaam = je naam), zodat ze doorlopen als je verbinding wegvalt.
- Voor je een GPU-job start: `nvidia-smi` checken en melden in de groep. C heeft voorrang voor de grote embedding-run.
- Batchgrootte zo kiezen dat je onder 20 GB blijft, zodat een tweede job nog past.

### Claude-budget ($80 voor alles)

- **Ook Claude Code verbruikt dit budget.** Elke vraag die je aan Claude Code stelt, telt mee.
- Standaard Haiku 5.5. Sonnet alleen na overleg.
- Verdeling: max. $15 voor labelen (B), max. $5 voor advies (D), de rest voor programmeren. Rond 16:00 aan de organisatoren vragen hoeveel er nog over is.
- Claude Code zuinig gebruiken: start elke sessie met "lees `SPEC.md`, werk alleen in map `X/`". Plak nooit datasets in de chat; laat een script ze lezen.
- Elke Claude-call in een script logt het aantal tokens naar `logs/claude_usage.csv`. D heeft die cijfers nodig voor de kostslide.
- De sleutel staat alleen in `.env` of een terminalvariabele. Nooit in chat, screenshot of commit.

## Tijdsplanning

De planning gaat ervan uit dat we rond 19:30 inleveren. De echte deadline moet nog nagevraagd worden; schuif de tijden mee.

| Tijd | Wat | Wie |
| --- | --- | --- |
| 13:45–14:30 | Inloggen, data downloaden, sample maken, modellen laden, repo-skelet, stubs pushen | iedereen |
| 14:30 | **Checkpoint 1:** de app toont de vier blokken op nepdata (stubs) | D |
| 14:30–16:00 | Elke slice werkt echt op de sample van 20k | iedereen |
| 16:00 | **Checkpoint 2:** end-to-end op de sample met echte cijfers, lelijk maar werkend. Budget navragen. Demobank kiezen. | iedereen |
| 16:00–18:00 | Volledige data draaien, zwakste stap verbeteren, evaluaties (testset, 100 handchecks, concurrenten) | iedereen |
| 18:00 | **Feature freeze.** Eindbestanden in `data/final/`, alles gemerged op `main` | iedereen |
| 18:00–19:00 | Architectuur- en kostslide, pitch schrijven, 60 s schermopname als back-up | D leidt, iedereen levert een getal |
| 19:00–19:30 | Twee keer repeteren, elkaar vragen stellen, repo zippen | iedereen |
| 20:30 | Server gaat uit | — |

## Juryvragen en open beslissingen

De jury gebruikt deze checklist. Elk antwoord is één zin, met een getal en een `n`, en iedereen moet ze allemaal kunnen geven.

| Juryvraag | Ons antwoord komt van | Slice |
| --- | --- | --- |
| Wie gebruikt de output, voor welke beslissing? | De zin uit "In één minuut" | D |
| Welke naamvarianten, tussenpersonen en sprongen in de data vonden jullie? | Top-50 handcheck, % tussenpersonen, markering 2026Q1–Q2 | A |
| Welk deel bouwden jullie níet met AI, en waarom? Wat scoorde de domste aanpak? | Normalisatie met regels; woordenlijst als basislijn voor AI-tags | A, B |
| Waar komen de labels vandaan, hoe ruizig zijn ze? | Claude-labels + 100 handchecks, overeenstemming in % | B |
| Hoe weten jullie dat het klopt? | Aparte testset van 300, precision/recall per taal | B |
| Hoe weten jullie dat de concurrentenlijst klopt? | Gekende concurrenten komen boven, per land nagekeken | C |
| Wat gebruikt het model eigenlijk? Kan dat een proxy zijn voor taal of bron? | F1 per taal en per land; bedrijfsnaam weggelaten uit de tekst bij embedden | B, C |
| Wat gebeurt er met 100× meer data? | Kost per extra bedrijf, GPU-uren, wat breekt (geheugen → DuckDB, updates → enkel nieuwe vacatures) | D |
| Toon 3 willekeurige successen, 3 mislukkingen, de slechtste slice | Vaste seed, uit de testset | B, D |
| Wat probeerden jullie dat niet werkte? | Iedereen noteert dit doorlopend in `NOTES.md` | iedereen |

**Open beslissingen**

- [ ] Eigenaar per slice invullen (tabel in Taakverdeling).
- [ ] Echte inleverdeadline navragen bij de organisatoren.
- [ ] Demobank kiezen om 16:00, op basis van de telling van A. Voorkeur: een Belgische of Nederlandse bank met genoeg vacatures (jury is Belgisch), anders een grote UK-bank.
- [ ] Restbudget Claude navragen om 16:00.
- [ ] De "decision models" uit de workshop (Jev, Torchcast Decision) eerst op Hugging Face controleren voor iemand erop bouwt. Logistische regressie blijft het plan.
