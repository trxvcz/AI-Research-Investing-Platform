# Zadania

## Kronos — plan dodatkowej funkcji i hostingu, 2026-11-02

- [x] Uzupełnić architekturę i master plan o opcjonalne scenariusze cenowe, osobny worker, kontrakty do zaprojektowania, cache i bramki; opisać lokalny pilot oraz warunkowe warianty hostingu. To ukończona dokumentacja, nie wdrożona funkcja.
- [ ] KR-00: zweryfikować darmowe świece EOD, licencje, PIT/korekty i politykę danych; przejrzeć kod/wagi/tokenizer oraz okres pretrainingu.
- [ ] KR-01: uzgodnić kontrakty szeregu świecowego, zadania i artefaktu prognozy; bez obchodzenia ograniczeń raportu v1.
- [ ] KR-02: tani test deterministyczny, następnie lokalny benchmark mini/small; zmierzyć czas, pamięć i koszt zasobów.
- [ ] KR-03: ustalić progi przed testem, porównać baseline w walk-forward/OOS, ocenić rozrzut scenariuszy i ograniczenia pretrainingu. Bez przejścia bramki nie włączać modelu.
- [ ] KR-04: osobny pipeline/worker z kolejką PostgreSQL, heartbeat/fencing, immutable wynikami, cache i limitami.
- [ ] KR-05: UI 5/20 sesji, baseline i wersjonowane powiązanie z raportem, bez przepisywania historii.
- [ ] KR-06: lokalny pilot; hosting po pomiarach i budżecie, przed publikacją auth/TLS, monitoring, backup/restore i niezależny QA. Brak wybranego dostawcy i zakupów.

Szczegóły i zależności: [architektura Kronosa](docs/architecture/kronos-scenarios.md), [roadmap KR-00–KR-06](docs/roadmap/issues.md#kronos--opcjonalne-scenariusze-cenowe-2026-11-02). Nie zmienia to priorytetu pierwszego rzeczywistego raportu fundamentalnego ani zakazu płatnych fallbacków.

Weryfikacja aktualizacji dokumentacji: npm test 4/4 PASS; walidacja definicji 29 JSON Schema PASS; eksport schematów `--check` PASS. Niezależny QA dokumentów i granic bezpieczeństwa: bez blokujących uwag, doprecyzowano wyłączenie schedulera z pilota. Pełna próba pytest nie zwróciła wyniku i została przerwana; nie deklarujemy nowego PASS testów Python ani integracji PostgreSQL. Bez zmian kodu, konfiguracji runtime, schematów, migracji i uruchamiania modeli; brak zakupu infrastruktury.

## Discovery we właściwym repo — 2026-10-30

- [x] Potwierdzić katalog i zapis; zachować zastany stan Git oraz pliki użytkownika.
- [x] Przeczytać instrukcje, master plan, kontrakty oraz zewnętrzny audyt i ADR; nie kopiować kandydata zmian.
- [x] Przygotować discovery, target-state, ADR-0001 i zadania z zależnościami/testami/szacunkami w `docs/architecture`, `docs/adr`, `docs/roadmap`.
- [x] Przegląd właściciela: 2026-10-30 zaakceptowano opcję A — Python/FastAPI + React jako cel, Node jako demonstrator.
- [x] P0-03a: zweryfikować oficjalny dostęp SEC dla pierwszego pilota; aktywowany wyłącznie publiczny odczyt submissions/companyconcept przez bramkę P4-00. [Dopuszczenie](docs/sources/SEC_EDGAR_ADMISSION.md).
- [ ] Zweryfikować pozostałe źródła i ich prawa/limity przed aktywacją. Brak płatnych fallbacków; SEC nie zatwierdza automatycznie cen EOD, modeli ani innych usług.

Szczegóły: [issues](docs/roadmap/issues.md), [ADR](docs/adr/0001-platform-architecture.md). Poniżej zachowany stan etapów startera; M0 nie oznacza realizacji docelowej architektury master planu.

## Pierwszy przyrost fazy 1 — Python

- [x] P1-00a: wejście i odpowiedź walidacji v1, jedna definicja Pydantic, generowane JSON Schema 2020-12, fixture i testy; legacy pozostaje bez migracji.
- [x] P1-01: środowisko Python 3.12, przypięte zależności, lokalne FastAPI health/ready/validate, testy, lint, typecheck i konfiguracja CI.
- [x] Niezależny QA i retest dwóch poprawek: końcowy newline oraz zbyt precyzyjne timestampy. 69 testów Python i 4 testy Node przechodzą.
- [x] P1-00b: kontrakt raportu v1, checksum/rewizje i bezstanowy inspector M0/v1; legacy bez automigracji i fikcyjnych dat. 154 testy Python + 4 Node PASS, niezależny QA i retest poprawek URL/UUID PASS.
- [x] P1-02a: PostgreSQL/Alembic, append-only raporty i liniowe rewizje, idempotencja i API zapisu/odczytu; testy równoległości, backup/restore i restart bazy. 205 Python + 4 Node PASS. [Kontrakt i start](docs/POSTGRES_REPORT_STORE.md).
- [x] P1-02b1: minimalny niezmienny rejestr instrumentów (UUID, symbol/MIC/waluta/typ, źródło i daty), API create/get/search, kontrolowane powiązania nowych raportów bez backfill; migracja0002. 295 Python +4 Node PASS, QA zakończony. [Rejestr](docs/INSTRUMENT_REGISTRY.md).
- [x] P1-02b2: trwały manualny ledger przebiegów i exact-byte raw snapshots, CAS/idempotencja, fail/resume, finalizacja na istniejącym raporcie, API i migracja0003. 416 Python +4 Node PASS, restore całego zestawu i niezależny QA. [Kontrakt i start](docs/RUNS_AND_SNAPSHOTS.md).
- [x] P1-02c: automatyczny worker deterministyczny, kolejka PostgreSQL, leases/fencing, maks.3 przejęcia, atomowe report+advance i finish/fail, odzyskiwanie po crash/restore, odczyt stanu API, CLI i fixture. 507 Python +4 Node PASS (2026-11-02), niezależny QA i poprawki. [Instrukcja](docs/AUTOMATIC_WORKER.md), [weryfikacja](docs/WORKER_VERIFICATION.md).
- [x] P4-00: bramka free-only dla przyszłych adapterów/gateway, dokładne opłaty Decimal, warunki i polityka danych, trwałe quota PostgreSQL (migracja0005), brak retry/refund/fallbacku oraz blokada opłat w selektorze Node. 605 Python +9 Node PASS, niezależny QA i regresja underflow. [Kontrakt i ograniczenia](docs/FREE_ONLY_PROVIDERS.md).
- [x] Po backupie zastosować migracje0004–0007 na właściwej bazie Docker; head0007, `/ready`200, zachowane stare rewizje, końcowy backup obejmuje dane SEC.
- [x] P2-01a: pilot adaptera SEC — trzy exact-byte zasoby, wewnętrzne receipts, bezpieczny cache/first_seen, CIK/listing/kontekst roczny USD, trwała quota i brak fallbacku; osobny pipeline sec-fundamentals-v1.
- [x] P2-02: pierwszy rzeczywisty raport Apple za2025 w PostgreSQL i JSON/HTML, partial (przychód/net income/marża); liczby porównane z10-K. 745 Python +9 Node PASS. [Odbiór](docs/SEC_VERIFICATION.md).
- [ ] P2-01b: dalsze metryki, 10-Q, poprawki10-K/A, starsze strony zgłoszeń, pozostałe waluty i historyczne reguły PIT; obecny pilot blokuje nieobsługiwane konteksty.
- [ ] Scheduler, automatyczny start/usługa i monitoring workera. Każdy kolejny adapter źródła dopiero po osobnej weryfikacji warunków dostępu i polityki danych. Ręczne advance nadal nie wykonuje algorytmów.
- [ ] Historyczne listingi i provider alias mappings, ticker changes/corporate actions/delistings przed użyciem rejestru jako historycznego uniwersum. Minimalny rejestr nie realizuje tego zakresu.
- [x] P1-03a: lokalny panel React/TypeScript, generowane typy OpenAPI, lista spółek/przebiegów, dokładne rewizje, źródła i JSON/HTML, host tylko do odczytu oraz launcher Windows. Regresja 752 PASS, poprawiony jeden fixture i retest panelu/eksportu 10/10 PASS; Node9/9, build i QA PASS (2026-11-04). [Zakres](docs/PANEL.md).
- [x] P1-03b1: jawne uruchamianie analizy AAPL/GOOGL/GOOG z panelu, idempotentne ponowienie i stan konkretnego przebiegu.
- [ ] P1-03b2: pełny generowany klient operacji API i PWA/offline. Dotychczasowa PWA nadal działa w Node.

Instrukcje: [backend](docs/BACKEND.md). Runtime Node zachowany; pełne M1 poniżej nadal nie jest ukończone.

Zakres raportu: [REPORT_CONTRACT_V1](docs/REPORT_CONTRACT_V1.md). Koperta, kontrola powiązań i trwałe rewizje działają; nie jest to gotowy silnik analiz, renderer ani pełne P5.

- [x] M0: samodzielny runtime demo, API, PWA shell, raporty, kontrakty, testy.
- [ ] M1: walidator JSON Schema 2020-12 na każdej granicy, legalne źródło danych point-in-time, brakujące/stare dane, testy kontraktowe.
- [ ] M2: gateway providerów, cache, atomowe rezerwacje budżetu, ewaluacja jakości i fallback.
- [ ] M3: fundamenty spółek/surowców, metody wyceny, źródła i niezależny reviewer.
- [ ] M4: technical + DSL discovery + backtest + walk-forward; blokada leakage.
- [ ] M5: raporty z pełnym provenance, interaktywne wykresy, PDF, dostępność PWA.
- [ ] M6: trwała kolejka, scheduler, powiadomienia, monitoring, auth, backup/restore, wdrożenie 24/7.
Każdy etap wymaga testów i zaakceptowanej bramki z ROADMAP. Nie rozpoczynaj automatycznie płatnego przetwarzania.


Weryfikacja końcowa2026-11-06: pełny zestaw769 PASS i1 błąd ANALYSIS_BUSY podczas równoległego rzeczywistego ponowienia GOOGL (blokada advisory wspólna dla schematów tej instancji PostgreSQL). Po zakończeniu wywołań panelu retest całego test_panel_launch.py11/11 PASS. Nie deklarujemy pojedynczego pełnego przebiegu770/770. Ruff/mypy/schematy/OpenAPI i Node9/9 PASS. Powtórzenie rzeczywistego UUID GOOGL zwraca ten sam report_id i revision1.

Weryfikacja mapowania:12/12 testów uruchamiania PASS, Ruff/mypy/schematy/OpenAPI PASS, Node9/9 PASS. Nowy raport Alphabet zawiera przychód i wynik netto; pozostaje partial ze względu na ograniczony zakres fundamentów, brak cen/wyceny i pozostałych sekcji.

- [x] P1-03c: oficjalny katalog SEC (Nasdaq/NYSE), jawne pobranie przez free-only/quota/pacing, lokalne immutable bajty+hash i atomowy wskaźnik, wyszukiwanie i wybór w panelu, dynamiczna tożsamość nowych analiz, zachowanie frozen replay. Rzeczywisty odbiór MSFT completed. [Zakres i ograniczenia](docs/PANEL.md).

Końcowy odbiór katalogu2026-11-06: pełna regresja809 Python PASS (338s), Node9/9 PASS, panel6/6 PASS i build PASS. Ruff/format/mypy/schematy/OpenAPI PASS. Niezależny przegląd transportu/cache/guardów bez nowych blokujących uwag; wskazany problem replay poprawiono i objęto testem. Potwierdzono rzeczywisty refreshkatalogu, wyszukanieMSFT i zakończoną analizę. Bez migracji.

- [x] P2-03a: implementacja rozszerzonych fundamentów SECv2 (gotówka, dwie części długu długoterminowego, OCF, capex, ograniczonyFCF), osobny pipeline i migracja0008 po backupie, panel i testy. [Zakres](docs/SEC_FUNDAMENTALS_V2.md).
- [x] P2-03b: rzeczywisty pilot Apple v2 ukończony2026-11-09, completed,7 dostępnych metryk iFCF, JSON/HTML i backup po imporcie, niezależnyQA bez blokujących uwag.
- [ ] P2-03c: dowodyHTTP404 oraz porównaniaYoY wymagają osobnych kontraktów.

Końcowa regresja2026-11-06:826 Python PASS (243.87s), Node9/9 PASS, panel8/8+buildPASS, Ruff/mypy/schematy/OpenAPI PASS. `/ready`200 oraz odczyt wcześniejszego raportuGOOGL200 po migracji. Pilotv2 pozostaje niedokończony z powodu quota20/20; brak deklaracji rzeczywistego raportuv2.

- [x] P1-03d: porównanie dwóch zapisanych analiz tej samej spółki, dokładne rewizje, zgodność okresu/jednostki/waluty, braki i niejednoznaczność bez zer, źródła i daty. Panel16/16 oraz Node9/9 PASS, buildPASS. Sprawdzono realne raportyGOOGL: netincome delta0, revenue missing→available bez delta/procent. Odbiór wizualny niedokończony przez błąd połączenia przeglądarki. Bez nowych pobrańSEC.

- [x] P1-03e: rozwijane metadane źródeł raportu, zgodność instrumentu/snapshotu/source_id/hash/URL/daty i pobieranie oryginalnych bajtów przez istniejący endpoint attachment. Panel20/20+buildPASS, Node9/9PASS, schematy/OpenAPIPASS. Realne źródłoGOOGL metadata/content200, zgodnyhash, attachment+nosniff. Bez nowych pobrańSEC, migracji i zmianbackendu.

- [x] P6-01a: trwała kolejka importu PostgreSQL, osobny wykonawca, lease/heartbeat/fencing i monitoring w panelu. Zadanie przeżyło restartAPI i zakończyło się raportem w osobnym procesie. [Odbiór](docs/DURABLE_TASKS.md).
- [x] GPW-00: discovery oficjalnych źródeł i ograniczeń praw/formatów. To ukończona dokumentacja, bez aktywacji źródeł.
- [ ] GPW-01: dopuścić konkretny kanał raportów emitenta i kontraktIFRS/ESEF; ceny/corporateactions/PIT wymagają oddzielnego źródła.
- [ ] P6-01b: pełny dziennik etapów zadań, rejestr żywych wykonawców i scheduler. Auth/TLS, supervisor/kontenery i testrestore przed wystawieniemVPS.

Końcowa weryfikacja2026-11-09:836 Python PASS, Node9/9PASS, panel24/24PASS iTypeScript/VitebuildPASS. Ruff/format/mypy/schematy/OpenAPIPASS. Po dwukrotnym uruchomieniu Start-TaskWorker.ps1 pozostał ten sam żywy proces; `/ready`200. Worker działa lokalnie w tle. VPS nie został wdrożony, GPW/predykcje pozostają nieaktywne.

- [x] GPW-01a: kontrakt rynku w nowych zadaniach i jawna granicaXWAR, bez cichego kierowania symboluGPW doSEC. To tożsamość i kontrola zakresu, nie aktywny adapterGPW.

Końcowy odbiór tożsamości rynku2026-11-09:839 Python PASS, panel26/26 ibuildPASS, Node9/9PASS, Ruff/mypy/schematy/OpenAPIPASS. Kontrola lokalnegoAPI:PKN+XWAR otrzymujeUNSUPPORTED_MARKET, istniejące zadanieApple zachowujeXNAS; `/ready`200. WznowionoDocker i taskworker po przerwie. Bez migracji. Dla prywatnego pilotaORLEN potwierdzonoHTTPSHEAD200, XLSX13143b oraz robotsDisallowpuste. ParserIFRS/PLN, importfinansowy i predykcjeGPW pozostają do wykonania.

- [x] P4-01a: wspólny agent szkicowania faktów z dokumentów, czytniki formatówtext/HTML/XLSX, kontrakty i cytaty/liczby/Decimal, adapterGemini bez aktywacji, brak publikacji niezweryfikowanych faktów. [Zakres](docs/DOCUMENT_RESEARCH_AGENT.md).
- [ ] P4-01b: potwierdzić projektGeminiFree/billing/model, skonfigurować klucz serwerowy i wykonać ograniczony benchmark różnych emitentów. GoogleAIPro nie jest dowodem darmowych wywołańAPI.
- [ ] P4-01c: PDF/OCR, wersjonowany audyt model/prompt/response i zadania dokumentowe w kolejce oraz bramka publikacji zweryfikowanych metryk.

Kontrola Gemini przed pilotem: klucz lokalny poprawny (models.list200), projekt Paid/Tier1+. Stały grant pozostaje nieaktywny. Późniejszy, osobno autoryzowany wyjątek testowy opisano w P4-01b1; nie zmienia on polityki produkcyjnej.

- [x] P4-01b1: jednorazowy autoryzowany pilot Gemini na danychsyntetycznych, HTTP200, szkic z poprawnym cytatem i liczbą needs_review, rezerwałączna0.894845PLN<1PLN. Nie jest to kwalifikacja jakości ani aktywacja stałegoPaid.
- [ ] P4-01b2: wielodokumentowy benchmark i jawny budżet operacyjny/bezpłatny projekt przed integracją modelu z kolejką i raportami.

Końcowy odbiór agenta dokumentowego 2026-11-10: 987 Python PASS na PostgreSQL Docker, Node 9/9 PASS, Ruff/format/mypy/schematy/OpenAPI PASS. Konfiguracja --env-file działa bez ujawniania wartości. Po pilocie nie wykonano kolejnych generacji; zapis odpowiedzi odtworzono offline. Bez migracji i bez aktywacji płatnego providera.

- [x] P4-01c1: niezmienne lokalne archiwum oryginalnych dokumentów i szkiców, hashe, deklarowane pochodzenie, deterministyczna rewalidacja i dopisywana historia przeglądu faktów; import i przegląd w panelu. Akceptacja nie publikuje obserwacji ani raportu. [Zakres i odbiór](docs/DOCUMENT_ARCHIVE.md).
- [ ] P4-01c2: wersjonowany audyt rzeczywistych wywołań modelu, zadania dokumentowe, PDF/OCR i osobna bramka publikacji zweryfikowanych danych. Wymagania kwalifikacji i budżetu modelu pozostają aktualne.

Odbiór archiwum 2026-11-10: 1039 Python PASS w jednym końcowym przebiegu, panel 34/34, Node 9/9 i build PASS; Ruff/format/mypy/schematy/OpenAPI PASS. Migracja0010 zastosowana po backupie z zachowaniem wcześniejszych danych; zapis i decyzja przetrwały restart panelu. Test pg_dump/restore zachowuje dokument i historię oraz umożliwia kolejną rewizję. Niezależny QA bez pozostałych blokerów po poprawkach Unicode/integrity/NOWAIT. Brak nowych wywołań modeli. GPW, predykcje i wdrożenie VPS nadal wymagają kolejnych etapów.
