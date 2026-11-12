# Weryfikacja przebiegów i surowych danych

Data: 2026-10-30. Gałąź `codex/p1-runs-snapshots`. Python 3.12.14, PostgreSQL 17.11, Node 24.21.0. Nie dodano nowych bibliotek ani wywołań modeli/dostawców.

## Wyniki

- **416 testów Python PASS**, bez pominięć, na docelowym PostgreSQL Docker; **4 testy Node PASS**.
- Ruff check/format: 41 plików, mypy: 18 modułów źródłowych, pip check i schema drift: PASS. Eksport 24 schematów v1; testy sprawdzają 28 schematów wraz z 4 legacy.
- Exact BYTEA roundtrip obejmuje JSON whitespace/CRLF, NUL i nonUTF8. Sprawdzane są SHA256, długość, kanoniczny base64, rozmiary i metadane. Identyczny retry, konflikty, równoległe próby, paginacja, nieznana dostępność i wykrywanie korupcji: PASS.
- Przebiegi: tworzenie z zamrożonymi wejściami, brak częściowego zapisu po błędzie, unknown/future availability, kolejność etapów, fail/resume przez nowy engine, idempotentne historyczne retry i równoległy CAS z jednym zwycięzcą: PASS.
- Finalizacja: poprawny raport, terminalny failed result oraz odmowa niezgodnego ID/hash/source/license/retrieved_at i obserwacji dostępnej wcześniej niż źródłowy snapshot: PASS. Report_status partial/blocked jest odrębny od zakończenia workflow.
- HTTP TestClient+PG: archiwizacja, odczyt bajtów, queued→start→advance→fail→resume→finish, odczyt stanu i historii oraz retry finish: PASS. To deklaracje manualnego przebiegu, bez rzeczywistego wykonywania analityki.
- pg_dump SQL i psql do osobnej bazy odtwarzają instrument, snapshot, FK i raport z checksum. Przebieg zapisany jako failed/validate zostaje wznowiony od validate i zakończony na powiązanym raporcie partial: PASS. Bajty po restore pozostają identyczne.
- Migracja0002→0003 zachowuje istniejący instrument i pełny raport/checksum na populowanych danych testowych. Append-only, metadata/digest guards, zamrożenie bindingów, sekwencje i bezpieczny downgrade NOWAIT: PASS.

Pierwszy pełny przebieg na bazie natywnej wykazał dwa założenia starszych testów o konkretnym head lub kolejności cofania późniejszych migracji. Test historycznej blokady został przypięty do właściwej migracji0001, a porównanie aktualnego head do MIGRATION_HEAD; nie zmieniano starych migracji ani nie osłabiono sprawdzanej ochrony danych. Końcowy pełny zestaw Docker przeszedł po poprawkach.

Pozostaje jedno znane ostrzeżenie Starlette/httpx w TestClient. Zdalnego CI i automatycznego workera nie uruchamiano. Istniejący job CI z PostgreSQL16 obejmuje nowe testy.

## QA i środowisko

Moduły migracji, snapshot store i research ledger powstały z rozłącznym właścicielstwem. Koordynator zintegrował kontrakty/API/testy oraz końcową bramkę PIT. Read-only QA wykrył obejście body cap przez root_path; poprawiono dopasowanie do ścieżki routera i dodano regresje dla prefiksu, chunked i fałszywego Content-Length. Niezależny retest PASS, aplikacja nie jest wywoływana po oversized body. Buffer używa bounded bytearray. QA potwierdził także konserwatywną bramkę availability obserwacji względem snapshotu.

Docker był początkowo ręcznie wstrzymany; próba odczytu panelu computer-use zakończyła się timeoutem zatwierdzenia dostępu, bez akcji UI. W tym czasie testy wykonano na wcześniej przygotowanym natywnym PostgreSQL na osobnym porcie 55433. Po wznowieniu Docker przez użytkownika wykonano lokalny pg_dump do ignorowanego katalogu backupów, migrację bazy deweloperskiej do `0003_runs_snapshots` i pełne testy kontenera. Zastany stan deweloperski zawierał 0 raportów i 0 instrumentów; zachowanie populowanych danych potwierdzają testy migracyjne. Do bazy deweloperskiej nie dodano próbek. Pomocniczy klaster testowy zatrzymano bez zmiany konfiguracji Docker ani danych jego wolumenu.

## Ograniczenia

Ledger nie jest workerem ani kolejką z leases/fencing. Actor i status etapu są deklaracją wywołującego; bez auth/RBAC nie stanowią poświadczenia tożsamości ani dowodu wykonania algorytmu. Finalizacja waliduje spójność danych/źródeł, nie prawdziwość tez, licencji i metod. Daty availability/retrieved pozostają deklaracjami do sprawdzenia przez adapter; created_at archiwum jest rzeczywistym zapisem serwera.

BYTEA jest ograniczone do 1 MiB na snapshot, do 32 wejść na run. Archiwum nie parsuje ani nie wykonuje danych. Administrator DB może wyłączyć triggery; to nie WORM. Brak auth i globalnego limitu body dla całego API; cap 1500000 dotyczy uploadu snapshotów. URL nie jest pobierany, a surowy plik jest tylko attachmentem.

Zachowano pliki użytkownika, master plan, historyczne migracje0001/0002 i raporty. Nie wykonywano stagingu, commita, resetu ani push. Nie kopiowano zmian z C:. Koszt lokalnych obliczeń i pracy nie był mierzony; brak opłat i wywołań API dostawców danych/LLM.
