# P1-00b — weryfikacja raportu i legacy

Data: 2026-10-30. Gałąź: `codex/p1-report-contract`. Zastane zmiany pozostawiono w repo; nie wykonywano stagingu, commita, resetu ani push. Nie kopiowano materiałów z C:.

## Zakres i wyniki

Dodano `report_contracts.py`, `legacy.py`, dwa eksporty schematów oraz bezstanowy endpoint `/v1/reports/inspect`. Wprowadzono syntetyczny snapshot i zapieczętowany przykład raportu; reguła LF w .gitattributes stabilizuje bajty fixture przy checkout na różnych systemach.

- Pełny `pytest -q`: **154/154 PASS** na Python 3.12.14/Windows. W tym test oryginalnego raportu wygenerowanego przez Node w katalogu tymczasowym: inspector nie zmienia bajtów plików.
- `npm test`: **4/4 PASS**, Node 24.21.0.
- Ruff check/format, mypy sześciu modułów, pip check: **PASS**.
- Kontrola driftu pięciu eksportów v1: **PASS**. Testy sprawdzają JSON Schema 2020-12 dla dziewięciu schematów wraz z walidacją formatów przy sprawdzaniu danych.
- HTTP w TestClient: poprawne v1 i M0, kompaktowa odpowiedź, błędny checksum/wersja/extra fields/ścieżka dają ogólne 422; OpenAPI opisuje unię wyniku po format. Nie dodano tworzenia ani odczytu zapisanych raportów.

TestClient i próba Node/tmp wymagały rozszerzonych uprawnień środowiska Windows. Pozostaje jedno ostrzeżenie deprecacji Starlette o httpx w TestClient; brak błędów testów. Nie uruchamiano Uvicorn jako osobnego procesu, przeglądarki, kontenerów ani zdalnego CI.

## Niezależny QA

Właściciel legacy.py/test_legacy.py pracował niezależnie od właściciela kontraktów/API. QA tylko do odczytu wykonał oddzielne próby bramek. Wykrył rozjazdy dopuszczalnego prefiksu URL oraz UUID bez myślników pomiędzy Pydantic i schema. Dodano reguły wejścia i testy regresyjne; niezależny retest obu poprawek **PASS**, także dla poprawnego HTTP(S)/UUID. Regresje poprzedniego przyrostu dotyczące newline i precyzji czasu nadal przechodzą.

Sprawdzono: exact source coverage, kolejność available_at/retrieved_at/generated_at, referencje tylko do dostępnych obserwacji, blokadę promocji partial do complete, failed z zachowaniem dostępnych wyników, rodzica rewizji, checksum po normalizacji UTC oraz brak fallbacku do M0 dla jawnej wersji. Jawny pusty registry legacy nie pobiera zewnętrznych referencji; test odrzuca obce URI lokalnie.

## Ograniczenia

Walidujemy deklaracje i spójność koperty, nie prawdziwość tez, obliczeń, snapshotu lub licencji. SHA klienta nie jest podpisem. Checksum wykrywa zmianę względem zadeklarowanego hasha, ale klient może ponownie zapieczętować zmienioną treść; potrzebny będzie zaufany magazyn i polityka publikacji. Model rewizji nie sprawdza istnienia rodzica ani ciągłości historii bez bazy. Pole pipeline_git_sha wskazuje deklarowany commit; nie dowodzi odtwarzalności kodu z lokalnymi zmianami. Fixture używa rzeczywistego SHA bazowego HEAD, nie twierdzi, że zawiera on wdrożony przyrost.

Brak auth, rate limit i globalnego limitu rozmiaru body: API lokalne. URL jest danymi, nie adresem do pobrania; tekst źródeł nie jest wykonywany. Brak dostawców danych, LLM, brokerów i zleceń. Wykresy i model_provenance w tym zakresie są jawnie niedostępne ([]/null), a renderowanie i trwałe wersjonowanie pozostają kolejnymi zadaniami.

Brak opłat/wywołań API dostawców. Nie dodawano ani nie pobierano nowych bibliotek w tym przyroście; wykorzystano przypięte jsonschema/referencing. Kosztu pracy i lokalnych obliczeń nie mierzono.
