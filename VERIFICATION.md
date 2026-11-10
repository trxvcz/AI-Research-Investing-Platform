# Weryfikacja — 2026-10-30

Poniżej zachowano historyczną weryfikację startera M0. Aktualna weryfikacja nowego backendu Python (69 testów + 4 Node, lint/typecheck/schema i QA) znajduje się w [docs/P1_VERIFICATION.md](docs/P1_VERIFICATION.md).

Nowszy przyrost raportu/legacy: [docs/P1_REPORT_VERIFICATION.md](docs/P1_REPORT_VERIFICATION.md), 154 testy Python + 4 Node PASS.

Najnowszy przyrost PostgreSQL: [docs/POSTGRES_VERIFICATION.md](docs/POSTGRES_VERIFICATION.md), 205 testów Python + 4 Node PASS, rzeczywisty backup/restore i restart bazy.

Nowszy przyrost rejestru: [docs/INSTRUMENT_REGISTRY_VERIFICATION.md](docs/INSTRUMENT_REGISTRY_VERIFICATION.md), 295 testów Python +4 Node PASS, migracja0002 i restore powiązań.

Najnowszy przyrost przebiegów/archiwum: [docs/RUNS_SNAPSHOTS_VERIFICATION.md](docs/RUNS_SNAPSHOTS_VERIFICATION.md), 416 testów Python +4 Node PASS, migracja0003 i wznowienie po restore.

- Node 24.21.0: npm test — 4/4 PASS (oba typy aktywów, niezmienne identyfikatory raportów, kolejność ról, odrzucenie przyszłych/błędnych danych, routing koszt/jakość, blokada niezaimplementowanego backtestu).
- npm run demo — PASS; zapis JSON/HTML/SVG z syntetycznymi danymi.
- Wszystkie JSON/manifest — parsowanie poprawne; wszystkie JS/MJS — kontrola składni poprawna.
- Raport demo — PASS walidacji Test-Json z contracts/report.schema.json, z lokalnym $defs analizy. Pełna walidacja wszystkich przyszłych payloadów w runtime pozostaje M1.
- API HTTP — PASS: health, ready, powłoka PWA, manifest, service worker, lista raportów, JSON/HTML/SVG; .env daje 404, POST daje 405.
- docker compose config --quiet — PASS. Build/start kontenerów NIE wykonany: brak aktywnego silnika Docker Desktop.
- Nie wykonano testu instalacji PWA w przeglądarce, renderowania wizualnego ani uruchomienia pliku Python. Demo nie wymaga Pythona. Nie testowano zewnętrznych providerów ani produkcyjnej infrastruktury.
- Żadne repozytorium GitHub nie było modyfikowane. Nie użyto kluczy API ani płatnych wywołań. Nie ma historycznych wyników inwestycyjnych.

Kontrola ZIP i SHA-256 opisana w pliku WERYFIKACJA.txt obok archiwum.
