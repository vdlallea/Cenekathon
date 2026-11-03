# Context
Ik ben eigenaar van slice D (map app/). Lees SPEC.md voor de contracten.

# Regels
- Werk alleen in app/, data/final/cards/ en logs/. Wijzig NOOIT SPEC.md of common/paths.py zonder te vragen.
- Nooit .env lezen. Nooit ruwe data of embeddings in git.
- Elke Claude-API-call logt tokens naar logs/claude_usage.csv.
- Model voor API-calls: claude-haiku-5-5. Nooit Sonnet of Opus.
- Geen verzonnen cijfers: elk getal in advies komt uit company_quarter, peers of salaries, of uit een expliciete aanname in app/assumptions.py.
- Plak nooit datasets in de chat; schrijf scripts die bestanden lezen.
