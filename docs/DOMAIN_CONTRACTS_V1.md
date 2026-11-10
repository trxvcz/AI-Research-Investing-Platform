# Kontrakty v1 — pierwszy przyrost Python

Status: wdrożony i przetestowany po akceptacji ADR-0001, 2026-10-30. Ten dokument opisuje walidację wejścia. Kopertę raportu i kontrolę legacy dodano w osobnym [REPORT_CONTRACT_V1](REPORT_CONTRACT_V1.md). Stare kontrakty M0 i raporty pozostają bez zmian; nie ma jeszcze zleceń research-run.

Źródło definicji: `services/backend/src/alphasense/contracts.py` (Pydantic v2). JSON Schema 2020-12 w `contracts/v1/` jest generowane; nie edytować ręcznie. Kontrole chronologii i unikalności są semantyczną walidacją Pydantic, nie regułami samego JSON Schema.

## ResearchInput

Wymagane: schema_version=`1.0`, instrument_id (1–128 znaków, bez białych znaków na brzegach), asset_type (`equity`, `etf`, `commodity`), as_of (RFC3339 ze strefą), data_origin (`synthetic`, `live`), observations (1–1000). Nie przyjmujemy instrukcji modelu, konfiguracji płatnego providera ani kodu.

Każda obserwacja ma metric (identyfikator `[a-z][a-z0-9_]{0,63}`), unit (1–64 znaki), currency (kod trzech wielkich liter albo null), period_start i period_end (RFC3339 ze strefą, start ≤ end). Waluta jest polem wymaganym, null oznacza wskaźnik bez waluty; weryfikacja ekonomicznego sensu jednostek wymaga późniejszego rejestru metryk. Unikalność: metric + unit + currency + okres po normalizacji stref.

Obserwacja to unia rozróżniana przez status:

- `available`: value jest skończoną liczbą JSON (zero poprawne; bool i string niedopuszczalne), source_id i snapshot_id są niepustymi identyfikatorami do 128 znaków, event_time i available_at są RFC3339 ze strefą. Obowiązuje period_end ≤ event_time ≤ available_at ≤ as_of. Identyfikatory są deklaracją klienta, nie dowodem autentyczności danych ani zweryfikowanej licencji.
- `missing` lub `not_applicable`: value musi być null, reason jest niepustym tekstem do 512 znaków. Nie dopisujemy fikcyjnego źródła ani daty dostępności. Okres nie może wykraczać poza as_of. Takiej obserwacji nie używamy jako historycznie udowodnionego braku danych.

Nieznane pola są odrzucane na każdej granicy. Timestamp jest stringiem JSON z precyzją najwyżej mikrosekund (maksymalnie 6 cyfr ułamka); liczba epoki oraz data bez czasu są niedopuszczalne. Wyższa precyzja jest odrzucana, aby obcięcie czasu nie ukryło danych dostępnych po as_of. Na wyjściu daty są normalizowane do UTC.

Wartość liczbowa -0.0 jest normalizowana do 0.0 przed hashowaniem i zapisem: PostgreSQL JSONB nie zachowuje znaku zera. Jest to nadal dostępna wartość zero, nigdy missing. Już zapieczętowany raport z hashem obliczonym dla odmiennej reprezentacji zostanie odrzucony zamiast zapisany ze zmienioną treścią.

## ValidationResult i API

`GET /health` i `GET /ready`: bez DSN mode=`validation-only`, research_only=true, external_providers_enabled=false. Po podłączeniu PostgreSQL mode=`postgresql`, /ready dodatkowo sprawdza połączenie, migrację i tabele; /health pozostaje liveness bez odpytywania DB. Ready nie dowodzi gotowości źródeł.

`POST /v1/validate`: przyjmuje ResearchInput, nie zapisuje danych ani nie wywołuje źródeł/LLM. Zwraca ValidationResult: schema_version, instrument_id, as_of, data_origin, status (`complete`, `partial`, `blocked`), available_count, missing_count, not_applicable_count. Complete oznacza wyłącznie kompletność zadeklarowanych obserwacji: co najmniej jedna available, zero missing; partial ma available i missing; blocked nie ma available. Nie oceniamy pokrycia wymaganych metryk ani jakości ekonomicznej.

Błędne wejście: HTTP 422 z ograniczonymi komunikatami (bez zwracania wartości wejściowych lub dokumentów). Nieistniejące zasoby research-runs, raportów i transakcji pozostają niedostępne. Swagger UI z CDN jest wyłączone; `/openapi.json` pozostaje lokalnym opisem API. Brak auth: serwer deweloperski tylko na 127.0.0.1, osobny port 8081 wobec Node na 8080.

## Legacy i następne kroki

Nie da się bezstratnie zmapować M0 do v1: stare raporty nie przechowują obserwacyjnego available_at, okresów i snapshotów. Nie wyprowadzamy ich z created_at/as_of. Legacy pozostaje czytelne przez Node, a `/v1/reports/inspect` rozpoznaje je ze statusem `blocked_missing_provenance`. Nie dokonuje migracji. P1-00 obejmuje obecnie wejście, odpowiedź walidacji i kopertę raportu z relacjami, nie pełny silnik raportowy i klient React.

Dokumentacja użytych bibliotek: [FastAPI — Request Body](https://fastapi.tiangolo.com/tutorial/body/), [Pydantic — JSON Schema](https://docs.pydantic.dev/latest/concepts/json_schema/). Generowane schematy i testy mają wykrywać rozjazd definicji; walidacja nie jest pobieraniem ani certyfikacją źródła.
