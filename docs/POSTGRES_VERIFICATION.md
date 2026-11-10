# Weryfikacja PostgreSQL i trwałych rewizji

Data: 2026-10-30. Gałąź: `codex/p1-postgres-revisions`. Python 3.12.14, PostgreSQL 17.11, Node 24.21.0. SQLAlchemy 2.1.6, Alembic 1.20.1, psycopg 3.3.6; zależności bezpośrednie i pośrednie przypięte w requirements-dev.lock.

## Potwierdzone

- **205 testów Python PASS**, bez pominięć, osobno na natywnym PostgreSQL i na PostgreSQL w Dockerze; **4 testy Node PASS**.
- Migracja upgrade, powtórny upgrade, zgodność tabel z metadata, wycofanie pustego schematu i odmowa downgrade niepustej historii.
- Deterministyczny test wyścigu downgrade/append: migracja czeka na transakcję i po jej commit odmawia usunięcia danych.
- Zapis i odczyt przez nowy engine, historyczne rewizje, keyset pagination, identyczny retry, konflikty rewrite/branch/skip/identity/time i globalnego revision_id, rollback nowego stream.
- Dwa równoległe appends: jedna nowa rewizja, drugi konflikt albo identyczny retry. Triggery odrzucają UPDATE/DELETE/TRUNCATE i niepoprawny bezpośredni INSERT.
- Odczyt wykrywa błędny payload/checksum/indeksowane metadane po symulowanym obejściu triggera przez właściciela testowego schematu.
- Rzeczywisty HTTP roundtrip przez TestClient + PostgreSQL: 201/200, GET latest/history/page, /ready. Osobne testy bez bazy pokrywają 404/409/422/503 i redakcję błędów.
- pg_dump SQL → psql w nowej bazie restore → odczyt raportu i zgodność obu hashy. Test usuwa tylko własną bazę restore i własny schemat.
- Dodatkowy smoke poza pytest: zapis dwóch rewizji, restart procesu PostgreSQL, odczyt obu hashy **PASS**. Usunięto wyłącznie utworzony do tego schemat.
- Docker Compose: config PASS, pull postgres:17.11, up --wait (healthy), migracja, pełny zestaw 205 testów PASS; następnie --force-recreate kontenera z zachowanym wolumenem i ponowny odczyt obu próbnych rewizji **PASS**. Klaster natywny zatrzymano, jego pliki pozostawiono bez usuwania.
- Przygotowano pustą bazę deweloperską `alphasense`, migrowaną do `0001_report_store`; check_ready rzeczywistego skonfigurowanego engine PASS. Nie dodano do niej syntetycznych raportów.

Ruff check/format (19 plików), mypy (9 modułów źródłowych), pip check, schema drift (8 eksportów v1), walidacja 12 schematów w testach i lokalne linki dokumentacji: PASS. Pozostało znane ostrzeżenie deprecacji Starlette/httpx w TestClient. Brak zdalnego CI, budowy obrazu aplikacji i publicznego wdrożenia.

## QA i poprawki

Niezależny read-only QA wskazał wyścig downgrade, NUL nieobsługiwany przez JSONB i ujemne zero zmieniające hash po odczycie JSONB. Dodano blokadę ACCESS EXCLUSIVE przed kontrolą downgrade, odrzucenie NUL z422 przed transakcją i normalizację signed-zero przed hashowaniem. RealPG probe potwierdził pierwotny błąd signed-zero, a regresja po naprawie przechodzi. Końcowy QA nie zgłosił dodatkowych blokujących uwag; testy DB wykonał koordynator.

Migracje powstały niezależnie; końcową poprawkę i API zintegrowano sekwencyjnie po zatrzymaniu delegacji. Zachowano zastany stan plików użytkownika, demonstrator Node, master plan, raporty i oryginalne schematy M0. Nie wykonywano stagingu, commita, resetu ani push.

## Środowisko i granice

Początkowo Docker Desktop nie udostępniał silnika; później uruchomił się poprawnie i końcowe testy wykonano także na kontenerze. Nie zmieniano ustawień wirtualizacji ani zabezpieczeń systemowych. Do wcześniejszych testów użyto przenośnego archiwum PostgreSQL17.11-5 z oficjalnej strony EDB. Lokalny SHA256 pobranego pliku: `80379b2c04d51c30225532e0ae04509899141e9957ed096fe749d7fd9df8f82f` — to lokalny pomiar, nie niezależnie potwierdzony podpis dostawcy. Wyodrębniono bin/lib/share do ignorowanego katalogu repo.

Windows AppControl zablokował pg_restore; nie zmieniano zabezpieczeń ani nie obchodzono blokady pliku. Wykonano standardowy backup SQL przez pg_dump i restore przez psql. Obecna baza działa w Dockerze tylko na 127.0.0.1:55432, z losowym hasłem w ignorowanych lokalnych plikach i danymi w wolumenie `alphasense-storage_postgres_reports`. Nie zainstalowano usługi PostgreSQL Windows. Testy i baza deweloperska nie korzystają z usług chmurowych.

Nie jest to WORM ani ochrona przed administratorem DB. Nie ma auth/RBAC, globalnego limitu body, pełnego instrument registry, kolejki/jobów i archiwum raw snapshotów. Przyjmujemy zwalidowany raport klienta; nie potwierdzamy prawdziwości jego licencji, źródeł i tez. Produkcja wymaga oddzielnej roli runtime, auth i procedur backupu z ustalonym RPO/RTO. Brak providerów danych/LLM, płatnych fallbacków i narzędzi transakcyjnych. Kosztu pracy i lokalnych obliczeń nie mierzono.
