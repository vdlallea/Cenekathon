# NOTES.md: werklog en overzicht

Dit bestand hoort bij SPEC.md (sectie Juryvragen: "Iedereen noteert dit doorlopend in NOTES.md"). Hier staan de feiten, beslissingen en open punten. Geen geheimen: wachtwoorden, tokens en API-sleutels horen hier nooit in.

Status op het moment van schrijven: **slice B (taggen) is niet klaar.** Het basisbestand voor Claude-labels loopt, het trainingsscript bestaat nog niet, en er zijn open beslissingen (zie onderaan).

---

## Deel B: taggen (persoon B)

### Wat slice B moet opleveren (contract)

Volgens SPEC.md, sectie Contracten:

| Bestand | Kolommen | Wie gebruikt het |
|---|---|---|
| `tags.parquet` (in `~/data/work/`) | `vacancy_id` str, `has_ai` bool, `ai_type` str (builder/user/governor/none), `confidence` float 0-1, `source` str (claude/model/keyword) | C en D |

Doel per vacature: AI ja/nee én type. Eerst een woordenlijst als basislijn, dan Claude-labels op een steekproef, dan een klein model (logistische regressie) op de embeddings van C dat de rest tagt. Evaluatie op een aparte testset van 300.

### Mappen en bestanden

Lokaal (Windows) en server (Linux) hebben dezelfde repo-structuur:

```
Cenekathon/
├── SPEC.md, NOTES.md
├── common/paths.py          alle paden op één plek (gedeeld door alle slices)
├── tagging/                 slice B
│   ├── baseline.py          keyword-basislijn -> tags.parquet
│   ├── prepare_samples.py   maakt labelset (1500) en testset (300)
│   ├── run_claude_labeler.py  labelt de labelset met Claude Haiku
│   └── llm_prompt_draft.txt prompt voor Claude (definities + regels + JSON-uitvoer)
└── data/work/               (lokaal) / /home/team6/data/work/ (server, gedeeld)
```

`common/paths.py` bepaalt waar data staat:
- Standaard: op de server `/home/team6/data/work/`, anders `<repo>/data/work/`.
- Overschrijven kan met de env-var `TEAM_DATA_WORK`.
- Logs: `CLAUDE_USAGE_CSV` = `<repo>/logs/claude_usage.csv` (lokaal/in de repo-clone), `CLAUDE_CHECKPOINT_JSONL` = `<DATA_WORK>/logs/claude_labels_checkpoint.jsonl` (gedeeld).
- Op `main` gebruikt de app (persoon D) dezelfde namen: `ROOT`, `FINAL_DIR`, `STUB_*`, `LOGS_DIR`, `USAGE_LOG`. Die zijn bewust behouden in het samengevoegde bestand.

### Scripts: wat ze doen

**`baseline.py`** (keyword-basislijn)
- Regex-woordenlijst per type. Prioriteit builder > governor > user.
- Builder: machine learning, deep learning, LLM, MLOps, ML engineer, AI engineer, data scientist, model training, en meer.
- Governor: AI-governance, responsible AI, EU AI Act, AI-audit, AI-ethiek, AI-risk.
- Model risk telt alleen als governor wanneer `AI` of `ML` (of "machine learning", "artificial intelligence") in dezelfde tekst staat. Kredietmodelvalidatie zonder die termen telt niet.
- User: Copilot, ChatGPT, AI-tools, prompt engineering, AI-assistent.
- Algemene AI-termen (generative AI, GenAI, artificial intelligence): `has_ai = True`, type `user` als fallback.
- Een kale "AI" telt bewust niet (anders zou bedrijfs-boilerplate meetellen).
- Output: `tags.parquet` met `source = keyword`, `confidence = 1.0`.
- Argumenten: `--sample`, `--out`.

**`prepare_samples.py`** (labelset en testset)
- Eerst de testset: 300 vacatures met een natuurlijke verdeling (geen weging). Gespreid over land, taal en jaar.
- Daarna de labelset: 1500 vacatures uit de rest.
  - 50% keyword-hits (`--hit-share 0.5`), 50% niet-hits.
  - BE en NL krijgen gewicht 2,5 (`--oversample-weight`). Alleen in de labelset.
  - Kolom `inclusion_prob` = k / groepsgrootte per groep. De trainer kan daarmee wegen (1/inclusion_prob).
- Taal komt uit `spine.parquet` als die bestaat, anders uit een stopwoord-heuristiek (en/nl/fr/de/other).
- Asserts: geen overlap tussen testset en labelset, geen dubbele ID's.
- Seed 42.

**`run_claude_labeler.py`** (LLM-labeler)
- Model: `claude-haiku-5-5` (SPEC.md noemt Haiku 5.5). Sonnet en Opus worden geweigerd in de code.
- Prompt: `llm_prompt_draft.txt` met placeholders `{vacancy_id}`, `{title}`, `{text}`. Andere accolades (het JSON-voorbeeld) blijven staan.
- Tekst wordt afgekapt op 6000 tekens.
- `max_tokens = 1024`. Eerder stond dit op 200, en dat knipte het antwoord af.
- Geen `temperature`-parameter: dit model accepteert die niet (HTTP 400).
- JSON-extractie: Markdown-codeblokken en tekst eromheen worden gestript. Elke `{` wordt geprobeerd tot er een geldig object uitkomt.
- Validatie: `has_ai` moet bool zijn, `ai_type` moet een van de vier waarden zijn, `has_ai` moet overeenkomen met `ai_type != none`, `confidence` moet tussen 0 en 1 liggen.
- Retries: 4 pogingen met backoff bij 429/5xx/netwerk en bij ongeldige JSON. Bij 400/401/403/404 stopt de run (fatal).
- Checkpoint: elke vacature wordt direct weggeschreven. Alleen `parse_ok=true` telt als klaar. Mislukte rijen worden bij een volgende run opnieuw geprobeerd. Hervatten gaat met hetzelfde commando.
- Usage-log: elke call (ook mislukte) krijgt een regel met input- en output-tokens en status, in `claude_usage.csv` (append).
- `--limit N` telt nieuwe vacatures per run, niet het totaal. Met `--limit` schrijft de uitvoer alleen de verwerkte rijen weg.
- Mock-modus (`--mock`): labelt met de keyword-basislijn zonder API-calls. Schrijft naar aparte mock-bestanden.
- Uitvoer: `claude_labels_1500.parquet` met `vacancy_id, has_ai, ai_type, confidence, source="claude", model, parse_ok, attempts, error`.

**`llm_prompt_draft.txt`**
- Vier definities, letterlijk zoals opgegeven: Bouwer, Gebruiker, Bewaker, Geen.
- Regels: AI-vacature = AI-skill als vereiste of taak; boilerplate telt niet; één type per vacature; bij twijfel builder > governor > user; model risk alleen met expliciete AI/ML; geen verzonnen skills.
- Uitvoer: alleen één JSON-object.
- Let op: de definities wijken licht af van SPEC.md (die heeft voorbeelden). We gebruikten de versie die jij gaf.

**`train_model.py`**: **bestaat nog niet.** Zie "Volgende stap".

### Wat we gedaan hebben (chronologisch)

1. **Mock-basislijn.** Eerst `baseline.py` met 5 verzonnen vacatures om de logica te testen.
2. **Eerste echte run.** `baseline.py` op `sample_20k.parquet` op de server. Geschreven naar `thomas/Cenekathon/data/work/tags.parquet`. Die oude stub (4 rijen) is gebackupt.
3. **Paden en model-risk.** `common/paths.py` gemaakt. Hardcoded paden verwijderd. Model-risk-regel geïmplementeerd. Prompt bijgewerkt.
4. **Sampling.** `prepare_samples.py` gemaakt. Testset en labelset getrokken (zie hierboven). Testset-vingerafdruk gecontroleerd: die bleef gelijk na wijzigingen.
5. **Oversampling BE/NL.** Gewicht 2,5 in de labelset. Resultaat labelset: GB 996, NL 404, BE 67, LU 33. Testset ongewijzigd.
6. **Labeler, eerste testrun.** Faalde met HTTP 400 "'temperature' is deprecated for this model". Parameter verwijderd.
7. **Labeler, tweede testrun.** 3 van 5 vacatures faalden met `parse_error`. Logs toonden `output_tokens = 200` bij elke fout: het antwoord werd afgekapt. Opgelost: `max_tokens` naar 1024, robuustere JSON-extractie, ruwe antwoorden in de logs, mislukte rijen worden opnieuw geprobeerd.
8. **Labeler, derde testrun.** Geslaagd. Checkpoint bevat 10 rijen met `parse_ok=true`.
9. **Git.** Branch `tagging/sample-prep`. Commits: `a04e9bb` (paden, model-risk, sampling, labeler) en `f7a2e9b` (samengevoegde `paths.py`, labeler op nieuwe padnamen). Niet gepusht.
10. **Data van A.** A heeft de spine gefilterd op contractlanden (BE/NL/LU/GB) en opnieuw gegenereerd. Daarbij is ook `sample_20k.parquet` opnieuw getrokken (15:33).

### Wat er nu klopt en wat niet

**Klopt:**
- De spine heeft unieke `vacancy_id`'s.
- De embeddings van de oude sample: 20.000 rijen, 768 dimensies, geen NaN's, ID-volgorde klopt met de ID-bestand.
- De labelset en testset hebben ID's die in die oude embeddings voorkomen (1500/1500 en 300/300).

**Klopt niet of is onduidelijk:**
- **De sample is vervangen.** Na A's herberekening staan maar 20 van de 1500 labelvacatures en 7 van de 300 testvacatures in de nieuwe `sample_20k.parquet`.
- **Er zijn geen embeddings voor de nieuwe sample.** `embeddings.npy` en `embeddings_ids.parquet` (het contract-pad) bestaan niet. Alleen `embeddings_sample_20k.npy` bestaat, en die hoort bij de oude sample.
- **De testset heeft geen Claude-labels.** Alleen keyword-labels. Metrics daarop zijn circulair.
- **Bug in mijn `prepare_samples.py`:** taal ontbrak voor vacatures die niet in de spine stonden, en die kregen de waarde `other`. In de labelset gaat het om 322 rijen; allemaal die uit de spine ontbraken.
- **Shared `tags.parquet`:** om 14:44 overschreven met de nieuwe keyword-versie. Backup: `tags_keyword_before_model_risk.parquet`. Om 14:28 stond er al een ander `tags.parquet` in de gedeelde map (dezelfde telling), waarvan de herkomst niet vaststaat.

### Huidige keyword-telling (20.000 sample-vacatures, na model-risk-regel)

| ai_type | aantal |
|---|---|
| none | 19.023 |
| builder | 728 |
| user | 208 |
| governor | 41 |

Totaal met een AI-hit: ca. 4,9%. Dat is zeldzaam, daarom de oversampling.

### Claude-labels: status

- Checkpoint op het moment van schrijven: 10 rijen klaar (`parse_ok=true`), van 1500.
- De laatste call in het usage-log was om 15:08:32. Daarna was er geen proces meer actief, en er staat geen fatale fout in het log.
- Een volledige run is op dit moment gestart door persoon B in tmux (zie hieronder).
- Labels zijn per vacature (op basis van de tekst). Labels blijven geldig voor vacatures die later nog in de labelset zitten. Vacatures die wegvallen bij een nieuwe trekking zijn verspild.

### Hoe je de labeler draait (persoon B)

Op de server, in tmux:
```bash
tmux new -s <naam>-label
export ANTHROPIC_API_KEY=...        # zelf intypen, niet plakken, niet opslaan in een bestand in de repo
cd ~/thomas/Cenekathon/tagging
~/venv/bin/python run_claude_labeler.py 2>&1 | tee -a ~/data/work/logs/claude_labeler_run.log
```
- Met `Ctrl-b d` laat je de sessie draaien. `tmux attach -t <naam>-label` om terug te komen.
- Hervatten na een onderbreking: hetzelfde commando. Klare vacatures worden overgeslagen.
- Tokens en kosten: `~/data/work/logs/claude_usage.csv`.
- Op de server staat geen `.env`. De sleutel moet dus in de sessie gezet worden.

Let op: de server-kopie van `common/paths.py` en `run_claude_labeler.py` is de versie van vóór de laatste padwijziging (`REPO_ROOT`, `LOG_DIR`). Die werkt op de server. Lokaal is de nieuwe versie gecommit (`f7a2e9b`). Synchroniseer niet zonder de andere kant te controleren.

Andere commando's:
```bash
# keyword-basislijn opnieuw draaien
~/venv/bin/python baseline.py --out /home/team6/data/work/tags.parquet
# labelset en testset opnieuw trekken (let op: verandert ID's)
~/venv/bin/python prepare_samples.py
# mock-test van de labeler (geen API, geen kosten)
~/venv/bin/python run_claude_labeler.py --mock --limit 3 --out /tmp/x.parquet --usage-csv /tmp/u.csv --checkpoint /tmp/c.jsonl
```

### Server en samenwerking

- Eén gedeelde Linux-gebruiker `team6` voor het hele team. Iedereen werkt in een eigen map (`~/<naam>/Cenekathon`).
- Inloggen: alleen met wachtwoord (geen SSH-sleutel ingericht). Het wachtwoord staat in het GPU-document. Alleen bereikbaar via het wifi van de locatie of eduroam.
- Gedeelde Python: `~/venv` (pandas 2.3.3, pyarrow 25.0.1, Python 3.10).
- Gedeelde data: `/home/team6/data/work/`. Alleen de eigenaar van een bestand schrijft het (SPEC.md).
- Lange jobs in `tmux`. Sessies op dit moment: `owen`, `thomas`, en de nieuwe labelsessie.
- De server gaat om 20:30 uit. Wat niet in git staat, is weg.

### Git

- Lokaal: branch `tagging/sample-prep`, gebaseerd op `main`.
- Commits: `a04e9bb`, `f7a2e9b`. Niet gepusht.
- Git-identiteit (alleen in deze repo, niet globaal): naam `thomasbintein`, e-mail `thomasbintein@gmail.com`.
- Commitberichten eindigen met `Co-Authored-By: Claude Haiku 5.5 <noreply@anthropic.com>`, conform de instructie.

### Beveiliging: wat nu rondzwerft

Tijdens het werk zijn meerdere geheimen in de chat geplakt. Dat is niet goed. Ze horen gewisseld te worden:
- Het **serverwachtwoord** (`team6`). Ook al wordt het alleen met een tijdelijk askpass-script gebruikt, het staat in de chatgeschiedenis.
- De **Anthropic-sleutel** uit `.env`, die meerdere keren in de chat verscheen.
- De **GitHub-token** die is geplakt. Zet die terug in GitHub en maak een nieuwe aan. Gebruik voor pushes `gh auth login`, dan staat er geen token in de chat.

Advies: wissel de sleutel en token, en richt een SSH-sleutel in op de server zodat het wachtwoord niet meer nodig is.

### Ontwerpkeuzes en aannames (om te controleren)

- **Generieke AI-termen** zonder specifiek type krijgen `user`. Een aanname, niet gevalideerd.
- **Kale "AI"** telt niet als AI-hit (boilerplate-risico).
- **Model risk** alleen met expliciete AI/ML. Volgt SPEC.md.
- **Oversampling** van BE/NL met gewicht 2,5 (aanbevolen 2 tot 3). Het gewicht is een keuze.
- **Testset** met natuurlijke verdeling: slechts ~14 keyword-hits van 300. Precision en recall op die set zijn daardoor ruw. Dit is een open beslissing.
- **Taalheuristiek** (stopwoorden) wordt alleen gebruikt als er geen spine is.
- **Tekst** van vacatures wordt afgekapt op 6000 tekens voor de labeler.
- **`temperature`** ontbreekt. Labels kunnen daardoor licht variëren tussen runs. Dat is een reproduceerbaarheidsrisico.

### Open beslissingen (wachten op jou of op A/C)

1. **Labelset en testset opnieuw trekken uit de nieuwe sample?** Dan verliezen we de meeste huidige labels. Of blijven we bij de oude set, die niet meer overeenkomt met A's sample? Beslissing van het team.
2. **Embeddings van C** voor de nieuwe sample (`embeddings.npy` + `embeddings_ids.parquet`). Zonder die kan inferentie niet op de nieuwe sample en niet op alle vacatures.
3. **Testset labelen met Claude.** Nodig voor eerlijke metrics. Extra kosten: ongeveer 300 calls.
4. **Testsetgrootte en hit-verdeling.** 14 positieven geeft ruwe precision/recall. Wil het team de testset verrijken met hits (dan moeten de metrics gewogen worden)?
5. **Locatie van het usage-log.** `paths.py` (nieuwe versie) zet het op `<repo>/logs/`. De lopende run schrijft nog naar de gedeelde map. Kies één plek.
6. **Pushen naar origin.** Nog niet gedaan. Akkoord van het team?
7. **Inferentie op volledige data.** Alleen mogelijk als C embeddings voor alle vacatures levert. Tot die tijd: alleen op de sample, en dat moet in de tekst van het contract duidelijk zijn.

### Volgende stap voor B

Zodra de Claude-labels klaar zijn en de beslissingen genomen:

1. **`train_model.py`** schrijven:
   - Labels inlezen (`claude_labels_1500.parquet`, alleen `parse_ok`).
   - Embeddings koppelen via `embeddings_ids.parquet`, nooit via rijvolgorde.
   - Logistische regressie op `ai_type` (en optioneel `has_ai`), met `class_weight` of `inclusion_prob`.
   - Evaluatie op de testset (300, met Claude-labels): precision/recall voor AI ja/nee, F1 per type, uitgesplitst per taal.
   - Inferentie: `tags.parquet` met `source = "model"` en `confidence` uit de modelkansen.
   - Ontbrekende embeddings afhandelen (rijen zonder vector krijgen een melding, niet stilzwijgend `none`).
2. **Metrics aan het team** geven voor de juryvragen (SPEC.md: "Waar komen jullie labels vandaan, hoe ruizig zijn ze?" en "Hoe weten jullie dat het klopt?").
3. **100 handchecks** (SPEC.md, slice B) voor de overeenstemming in procenten.
4. **Keyword versus model**: vergelijkende tabel voor de juryvraag.

### Update: testset labelen, trainingsscript, dry-run

- **Labelset en testset opnieuw getrokken** uit A's nieuwe sample (`prepare_samples.py` op de server). Resultaat: labelset 1500 (GB 1042, NL 339, BE 81, LU 38; taal en/nl/fr), testset 300 (13 keyword-hits). Geen `other` meer: alle vacatures staan in de spine. Testset en labelset overlappen niet (assert).
- **`run_claude_labeler.py`** heeft nu `--dataset labels|test`. `labels` schrijft `claude_labels_1500.parquet` met checkpoint `logs/claude_labels_checkpoint.jsonl`. `test` schrijft `claude_test_300.parquet` met eigen checkpoint `logs/claude_test_checkpoint.jsonl`. Tokens gaan beide naar `claude_usage.csv`. Alleen padnamen die in zowel de lokale als de server-`paths.py` bestaan, zodat er niets in `common/paths.py` hoeft te veranderen (dat bestand staat op "alleen via PR").
- **`train_model.py`** is geschreven en getest met nepdata (zie hieronder). Het wacht op `embeddings.npy` + `embeddings_ids.parquet` (`--wait-minutes`), koppelt op ID, traint `LogisticRegression` (sklearn 1.7.2 op de server), weegt met 1/inclusion_prob, evalueert op de testset (AI ja/nee, F1 per type, per taal, en de keyword-basislijn ter vergelijking), en schrijft `tags.parquet` met `source="model"`. Een bestaand `tags.parquet` wordt eerst naar een back-up met tijdstempel gekopieerd.
- **Dry-run op de server** (`/tmp/dry`, mock-labels en willekeurige embeddings, dus geen echte cijfers): labeler-mock voor beide sets OK; hervatten OK (5 + 295); ontbrekende embeddings geven een nette fout; contract gecontroleerd: kolommen `vacancy_id, has_ai, ai_type, confidence, source`, geen NULL's. Die controle vond een bug (`source` was `None` voor de meeste rijen door een Series van lengte 1). Gefixt.
- **Status:** de volledige Claude-run op de labelset draaide nog op de *oude* labelset toen de nieuwe werd getrokken. Zie "Open punten".

---

## Deel A, C, D

Nog niet toegevoegd. Elk teamlid voegt hier een eigen sectie toe met dezelfde opzet: wat gedaan, beslissingen, open punten.
