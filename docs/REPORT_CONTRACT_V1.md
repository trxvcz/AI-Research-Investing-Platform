# Raport v1 i zgodność legacy — P1-00b

Zakres: kontrakt i bezstanowa walidacja raportu JSON, bez generowania analiz, zapisu, migracji i renderowania HTML. Node M0 i istniejące raporty pozostają bez zmian. Źródło modelu v1: `report_contracts.py`, eksport w `contracts/v1/report.schema.json`.

## Przyjęty kontrakt

ReportContent zawiera schema_version=`1.0`, report_id i revision_id (UUID), parent_revision_id (UUID lub null), revision (dodatnia liczba całkowita), generated_at_utc, input (ResearchInput), status (`complete`, `partial`, `blocked`, `failed`), methodology_version, pipeline_git_sha (pełne 40 lub 64 małe znaki hex), sources, cztery sekcje (`fundamental_section`, `technical_section`, `synthesis_section`, `scenario_section`), uncertainties, limitations i disclaimer. Model i prompt są jawnie null: `model_provenance`, `prompt_template_version`. chart_artifact_ids musi być pustą listą: schemat wykresu będzie osobnym zadaniem, bez akceptacji fikcyjnych artefaktów.

ReportRevision dodaje input_sha256 i checksum (64 małe znaki hex). Funkcja seal_report przyjmuje zwalidowany ReportContent, wylicza oba hashe i ponownie waliduje ReportRevision. Normalizacja: model_dump(mode=json) po UTC i normalizacji signed-zero, JSON UTF-8, ensure_ascii=false, sort_keys=true, separators=(',', ':'), allow_nan=false. input_sha256 obejmuje wyłącznie input. checksum obejmuje wszystkie pola raportu poza checksum. To wykrywa zmianę treści, nie jest podpisem ani gwarancją niezmienności magazynu. generated_at_utc ≥ input.as_of. Pierwsza rewizja nie ma rodzica; kolejne wymagają rodzica innego niż własne revision_id. Istnienie i ciągłość łańcucha egzekwuje osobny [magazyn PostgreSQL](POSTGRES_REPORT_STORE.md).

SourceProvenance: source_id, snapshot_id, sha256, url (HTTP(S) lub null), retrieved_at (timestamp UTC), license (niepusty tekst). Pary source_id/snapshot_id muszą być unikalne i dokładnie pokrywać obserwacje available. available_at ≤ retrieved_at ≤ generated_at_utc. Dla live URL jest wymagany; dla synthetic może być null. Walidator nie pobiera URL, nie sprawdza treści snapshotu ani prawdziwości deklarowanej licencji. Znacznik live i hash klienta nie dowodzą autentyczności źródła.

UUID wejściowy wymaga postaci 8-4-4-4-12 z myślnikami; na wyjściu jest małymi literami. URL musi mieć jawny prefiks HTTP(S) `://` i nie może zawierać whitespace; Pydantic dodatkowo waliduje URL i normalizuje host/path przed hashowaniem. Schema kontroluje prefiks oraz format URI; pozostałe reguły URL i relacje między polami są sprawdzane w modelu.

Każda sekcja ma status, findings i reason. Complete wymaga findings i reason=null; partial wymaga findings oraz reason. Blocked/failed/not_applicable wymagają reason i pustych findings. Finding ma kind (`fact`, `calculation`, `assumption`, `interpretation`), text (do 512 znaków), observation_indexes (unikalne indeksy available w input, maks. 1000), method (Identifier lub null). Fact/calculation/interpretation wymagają referencji; assumption może ich nie mieć. Calculation wymaga method, pozostałe mają method=null. To walidacja powiązania, nie dowód prawdziwości tekstu ani poprawności obliczenia.

Status raportu jest sprawdzany deterministycznie: dowolna failed sekcja → failed; brak dostępnych danych lub brak complete/partial sekcji → blocked; kompletne zadeklarowane dane i wszystkie sekcje complete/not_applicable → complete; pozostałe → partial. Complete nadal nie dowodzi pokrycia metryk wymaganych do pełnej analizy. Limitations: 1–32 pozycji, uncertainties: 0–32; żadnych pustych wyjaśnień. Disclaimer ma stałą treść: `Research only. No order execution or personalized investment advice.`

## Legacy i API

`POST /v1/reports/inspect` otrzymuje obiekt JSON, nigdy ścieżkę pliku ani URL do pobrania. Pole schema_version zawsze wybiera walidację v1; nieznana wersja lub zły v1 daje HTTP 422, bez próby degradacji do M0. Bez schema_version dokument musi przejść oryginalny `contracts/report.schema.json` z format validation; NaN/Infinity są odrzucane. Schemat legacy jest ładowany tylko ze stałej ścieżki w repo i nie ma zdalnego rozwiązywania referencji.

ReportInspection to unia po format:

- `v1`: schema_version=`1.0`, report_id, revision_id, revision, status, data_origin, checksum. Zwracamy tylko metadane, nie treść/narrację.
- `legacy-m0`: report_id (stare id), legacy_status (oryginalny status M0), migration_status=`blocked_missing_provenance`, missing_fields=`["observation_available_at", "observation_periods", "snapshot_provenance"]`. Nie przypisujemy v1, live ani complete; legacy_status nie jest oceną jakości. created_at/as_of/input_hash nie zastępują dostępności poszczególnych obserwacji.

Nieprawidłowe raporty dają ogólne 422 bez wartości danych, kontekstu błędu lub nieznanych nazw pól. Inspector nie nadpisuje, nie zapisuje i nie podnosi wersji raportów. Schema metadanych inspection jest eksportowane jako `report-inspection.schema.json`. Stare raporty nadal można czytać przez Node. Trwałe rewizje są dostępne przez osobny magazyn PostgreSQL; pełny kontrakt wykresów, obliczeń, model invocation i renderowanie wymagają następnych zadań.
