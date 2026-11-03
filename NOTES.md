# NOTES

Doorlopend logboek van het team (SPEC.md, sectie Juryvragen). Eén blok per slice; noteer ook wat niet werkte.

## Slice A · Data spine

### Wat er gebouwd is
- `spine/process.py`: leest de ruwe Parquet-bestanden, maakt een steekproef van 20.000 (seed 42), stript HTML, ontdubbelt (zelfde titel + bedrijf + eerste 200 tekens, binnen 30 dagen), normaliseert bedrijfsnamen naar groepsniveau, markeert tussenpersonen, bepaalt taal en kwartaal, en schrijft `spine.parquet` en `companies.parquet`.
- Uitvoer op de server in `~/data/work/`: `spine.parquet`, `companies.parquet`, `sample_20k.parquet`.

### Cijfers (definitieve run)
| Stap | Aantal |
| --- | --- |
| Ruwe vacatures | 1.542.169 |
| Zonder datum (weggelaten) | 271 |
| Duplicaten verwijderd | 315.981 (ongeveer 20%) |
| Land buiten BE/NL/LU/GB (weggelaten) | 4 |
| **spine.parquet** | **1.225.913** |
| **companies.parquet** | **1.317** bedrijven |
| Tussenpersonen | 2,4% (op naam 2,2%, op tekst 0,2%) |
| Taal | en 85,5%, nl 12,5%, fr 1,9%, de 0,2%, other 0,04% |

De sample van 20.000 is getrokken uit de ontdubbelde spine. Alle 20.000 IDs staan in de spine.

### Handcheck top 50 (groepering)
**Gecorrigeerd:**
- Eigen werving (`NN Careers`, `Natwest Careers`, `Deutsche Bank Careers`, `Santander Careers`, `JPMC Candidate Experience page`, en dergelijke) wordt bij de groep gerekend, niet als apart bedrijf.
- Aliassen: `Bank of America` (was `of-america`), Citi/Citigroup, JPMorgan Chase/JPMorganChase/J.P. Morgan, WTW/Willis Towers Watson, Santander/Banco Santander, AXA Partners, Allianz Partners, People's Partnership, Broadridge (met en zonder ", Inc.").

**Open, team beslist:**
- **Yource Group** (NL, 6.471 vacatures) staat als bedrijf. Het lijkt een recruiter, maar dat is niet geverifieerd.
- **BNP Paribas Fortis** staat nu bij BNP Paribas. SPEC.md noemt Fortis als aparte concurrent van KBC.
- **Verzekeringsmakelaars** (Aon, WTW, Howden, Gallagher, Marsh McLennan) blijven bedrijven. Volgens de SPEC-definitie zijn het geen tussenpersonen.

### Tussenpersonen
- Toegevoegd aan de regex: StudentJob, Konvert Interim, XTRA Interim, beBee, WhatJobs, ITZU JOBS, Alexander Mann Solutions, Proactive/MW Appointments, YouConnect, i3 Resourcing, Talent&Pro, Start People, LGBT Great Careers, Career Wallet, Jobs for Humanity, Nexus Jobs, caia Jobboard, en de eerder genoemde jobsites en uitzendbureaus.
- **Onzeker, niet gemarkeerd:** Tasker & Partners, Fairbank Partners, Greenwich Partners, Dojo Careers, Azuro Careers BV, Santander Resourcing.
- **Niet gemarkeerd, bewust:** Evelyn Partners, Baldwin Risk Partners, Openwork Partnership (vermogensbeheer en verzekeringsmakelaars, geen recruiters).

### Duplicaten (steekproef van 20 groepen)
- Van de 20 willekeurige groepen liggen er 11 binnen 30 dagen. Die worden verwijderd, zoals de SPEC voorschrijft.
- 9 groepen liggen meer dan 30 dagen uiteen. Dat zijn herplaatsingen; die blijven staan.
- Mediane spreiding binnen een dubbelgroep: 29 dagen. Over alle dubbelgroepen (205.082) ligt bijna de helft meer dan 30 dagen uiteen.
- **Beperking:** herplaatsingen na 30 dagen tellen mee in de aantallen. Dat moet bij de interpretatie van aandelen worden meegenomen.

### Bekende beperkingen
- Taaldetectie is een stopwoordentelling, geen `langdetect`. Rijen met te weinig stopwoorden krijgen `other`.
- De aliaslijst is een startset voor de grote groepen. Fuzzy matching gebruikt een drempel van 92.
- De company-IDs kunnen nog wijzigen na de handcheck. Gebruik `companies.parquet` als bron.

### Wat niet werkte (en hoe we het oplosten)
- Sample getrokken uit de ruwe data vóór ontdubbelen. Gevolg: ongeveer 20% van de sample-IDs stond niet in de spine. **Opgelost:** sample opnieuw getrokken uit de ontdubbelde spine (seed 42). De oude sample staat als `sample_20k_raw_old.parquet`.
- Eerste aliasversie maakte `of-america` van Bank of America en splitste de Citi- en JPMorgan-groepen. **Opgelost** in de tweede versie.
- PR #14 was gebaseerd op een oude branch en zou werk van anderen teruggedraaid hebben. **Vervangen door PR #15**, opnieuw gebouwd op `main`.
- Eerste test op een bestand van 117.000 rijen (2021) liet zien dat het script werkt, maar de volledige run duurde ruim 15 minuten. Dat is nu meegenomen in de planning.
