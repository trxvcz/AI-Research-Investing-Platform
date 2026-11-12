# Zadania

## Eksport gotowej analizy — 2026-11-12

- [ ] P5-02a: deterministyczny pełny eksport JSON i statyczny HTML, wybrany zapisanyAIv1/v2 lub jawny brakAI, historia/wskaźniki/dowody i kontrola tożsamości. [Zakres](docs/RESEARCH_EXPORT.md). Implementacja i odbiór w toku.


## Wykresy historii — 2026-11-12

- [x] P5-01a: interaktywne wykresy wyników i wskaźników z istniejących zweryfikowanych danych, wybór metryki/punktu, dokładne wartości i okresy, klawiatura, przerwy przy brakach/nieporównywalności; tabele i dowody zachowane. [Odbiór](docs/HISTORY_CHARTS.md). Bez pobrań, migracji i modelcalls.


## Wskaźniki fundamentalne — 2026-11-12

- [x] P2-04a: wskaźniki marż/przepływów z archiwum SEC, zgodne okresy/publikacja, dokładna arytmetyka i niezależna walidacja panelu, wzory/dowody; bezLLM i zmian starych raportów. [Zakres](docs/FINANCIAL_RATIOS.md). Odbiór rzeczywistego HTTP/UI i niezależnyQA zakończone.

## Gotowa interpretacja AI — 2026-11-11

- [x] P4-02a: polska narracja AI z cytowaniami dostępnych obserwacji, zapis związany z dokładną rewizją raportu, jawny przycisk generacji, historia i odczyt bez kolejnych wywołań. [Zakres i użycie](docs/AI_ANALYSIS.md).
- [x] P4-02b: osobna zgoda Gemini Paid, potwierdzenie obecnego klucza Paid/Tier1, nieodnawialne 50PLN i atomowa rezerwacja 1PLN na próbę w PostgreSQL; bez refundów/retry/fallbacku. Migracja0015 po backupie i kontroli zachowania raportów. FreeOnlyGateway niezmieniony.
- [x] P4-02c: nowy pilot narracji v3:3/3 syntetyczne odpowiedzi i niezależna ocena semantyczna; rzeczywiste zapisane GOOGL/AAPL, idempotentny odczyt i ponowne żądanie bez naliczenia kolejnej próby. Pierwsza odrzucona próba v2 zachowana i liczona.6PLN rezerwacji,44PLN pozostało. To zakres pilota, nie uniwersalna kwalifikacja lub wynik benchmarku ekstrakcji.
- [ ] P4-02d: szerszy benchmark narracji i zakresów długu, rozszerzenie porównywalnej historii/danych; odświeżenie przeglądu cen/warunków przed wygaśnięciem pilota bez resetu limitu. GPW/predykcje/Oracle nadal osobnymi etapami.
- [x] P4-02d1: odczyt maks3rocznych okresów z dokładnych archiwów raportu SEC, kwoty/r/r, kontrola tej samej publikacji i porównywalności, tabela panelu i pochodzenie; bezLLM lub zmiany starych raportów. [Zakres](docs/FINANCIAL_HISTORY.md). GOOGL2serie iAAPL4serie po3okresy2023–2025, bez nowych rezerwacji.
- [x] P4-02d2: zamrożony kontekst historii i cytowania, prompt report-history-v2, migracja0016 z zachowaniem v1/budżetu, ograniczona kwalifikacja4scenariuszy i rzeczywisteGOOGL/AAPL. [Zakres i ograniczenia](docs/AI_HISTORY_ANALYSIS.md). Szerszy benchmark pozostaje P4-02d.

Odbiór historii2026-11-11:1555PythonPASS/1SKIP wpełnejregresji, panel83/83, Node9/9 i buildPASS; Ruff/format/mypy/schematy/OpenAPI/pipcheckPASS.37testów parsera i4API, niezależnyQA oraz rzeczywistearchiwa/HTTP/walidatorpaneluPASS. Jednostki sprawdzone na raportachSEC(unitcurrency), późniejsze publikacje nie zastępują kotwicy. TabelaGOOGL2023–2025 potwierdzona winterfejsie; raporty/AIhashy i44PLN rezerwy bez zmian. Bez migracji, nowych pobrańSEC, generacjiLLM i wdrożeniaOracle.

Odbiór:1512PythonPASS/1SKIP, osobno1rzeczywistybackup/restore nowego audytu i limituPASS oraz30testówAPI po końcowej poprawcehealth/ready. Panel73/73, Node9/9 i buildPASS; Ruff/format/mypy/schematy/OpenAPIPASS.22testy PostgreSQL obejmują współbieżność64prób->50rezerwacji, niezmienność i brak resetu. Apple przydatna z widoczną uwagą o ograniczonym zakresie dwóch części długu; oryginalne teksty AI zachowane. Odbiór interfejsu potwierdził rzeczywiste wyniki, nowszy raportdomyślnie i schowane zaplecze.

Końcowy restart lokalnych usług zachował oba zapisane wyniki i44PLN pozostałego limitu; /ready200 pokazuje aktywneAI. Nowa kopia pg_dump po analizach, bez kolejnych generacji. Oracle nadal niewdrożone.

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
- [x] P4-01b2a: lokalny evaluator zapisanych szkiców, zamrożone dokumenty/gold/odpowiedzi z hashami, dokładne metryki TP/FP/FN i abstencje, CLI oraz syntetyczny zestaw regresyjny. [Użycie i ograniczenia](docs/DOCUMENT_BENCHMARK.md). To test narzędzia oceny, bez kwalifikacji Gemini, wywołań modeli i zmiany provider-policy.
- [x] P4-01b2b: prywatny corpus builder/verifier z oryginałami i dokładnymi wycinkami, datami i gold; lokalne materiały ORLEN/Microsoft/Apple oraz niezależny przegląd adnotacji. [Zakres](docs/BENCHMARK_CORPUS.md). Zestaw ujawnił ograniczenia istniejącego parsera tabel i separatorów; nie wykonano benchmarku modelu ani aktywacji źródeł.
- [x] P4-01b2c: wersjonowane czytanie tabel HTML i jawne reguły en-US, zachowanie odtwarzania starych dokumentów/hashów, utrwalanie opcji w archiwum/korpusie, panel i CLI. [Zakres i odbiór](docs/TABLE_READER_V2.md). Ręczny test rzeczywistych próbek daje5TP/0FP/0FN i1abstencję; nie jest to wynik modelu.
- [x] P4-01b2d1: zamrożony protokół developerskiego pomiaru GeminiFree, potwierdzenie konta powiązane lokalnie z kluczem,8syntetycznych promptów bezgold, trwała rezerwacja oraz adapter jawnego receipt odpowiedzi. [Rzeczywisty przebieg i ograniczenia](docs/GEMINI_FREE_QUALIFICATION.md). Pierwszy pomiar zatrzymany przed siecią przez błąd instrumentacji;0generacji, bez ponowienia. Poprawka audytu sprawdzana offline.
- [ ] P4-01b2d2: nowy ograniczony przebieg po poprawce audytu, wszystkie8odpowiedzi i ocena zamrożonego progu. Dotychczasowy przebieg nie daje wyniku jakości ani kwalifikacji rzeczywistych raportów. Provider/worker nadal wyłączone.

Odbiór przygotowaniaGeminiFree2026-11-11:1470PythonPASS/1SKIP w pełnej regresji PostgreSQL oraz osobno dodatkowy test rzeczywistego konstruktoraHTTPS bezsieci; transporty63/63, panel61/61, Node9/9 i buildPASS. Ruff/format/mypy/schematy/OpenAPI/pipcheckPASS. Niezależny przegląd poprawionego adaptera bez blokujących uwag. Pierwszy pomiar0generacji: lokalny błąd instrumentacji, potwierdzony reprodukcją offline;1rezerwacja zachowana, brak retry, jakości nie oceniono. /ready200; bez migracji i zmian produkcyjnej polityki modelu.

Odbiór korpusu2026-11-10:1392PythonPASS,1SKIP (symlinkWindows); zakresPOSIX59/59PASS bezsieci. Odbiór tabelv2 2026-11-11:1443PythonPASS i1SKIP w pełnym przebiegu, osobno2/2nowych testówCLI; panel56/56, Node9/9 i buildPASS, Linux43/43PASS. Ruff/format/mypy/schematy/OpenAPIPASS. Końcowy przegląd wykonał koordynator po limicie podagenta; korpus i gold miały wcześniejszy niezależnyQA. Po wznowieniuDocker i zatwierdzonej rotacji lokalnego hasła baza/panel/3roleworkerów działają, wcześniejszyGOOGL200. Bez migracji, nowych wywołań modeli i wdrożeniaOracle.

Odbiór evaluatora2026-11-10:1334PythonPASS w jednym pełnym przebiegu, w tym50nowych testów, Node9/9 i panel53/53PASS; Ruff/format/mypy/schematy/OpenAPI/pipcheckPASS. NiezależnyQA bez blokujących uwag. Referencyjne odpowiedzi ręczne i kontrolowane błędy semantyczne ocenione zgodnie z oczekiwaniem; zawsze not_qualified_offline. Bez migracji, modelcalls, zmianAPI/panelu i wdrożeniaOracle.

Końcowy odbiór agenta dokumentowego 2026-11-10: 987 Python PASS na PostgreSQL Docker, Node 9/9 PASS, Ruff/format/mypy/schematy/OpenAPI PASS. Konfiguracja --env-file działa bez ujawniania wartości. Po pilocie nie wykonano kolejnych generacji; zapis odpowiedzi odtworzono offline. Bez migracji i bez aktywacji płatnego providera.

- [x] P4-01c1: niezmienne lokalne archiwum oryginalnych dokumentów i szkiców, hashe, deklarowane pochodzenie, deterministyczna rewalidacja i dopisywana historia przeglądu faktów; import i przegląd w panelu. Akceptacja nie publikuje obserwacji ani raportu. [Zakres i odbiór](docs/DOCUMENT_ARCHIVE.md).
- [ ] P4-01c2: wersjonowany audyt rzeczywistych wywołań modelu, zadania dokumentowe, PDF/OCR i osobna bramka publikacji zweryfikowanych danych. Wymagania kwalifikacji i budżetu modelu pozostają aktualne.

Odbiór archiwum 2026-11-10: 1039 Python PASS w jednym końcowym przebiegu, panel 34/34, Node 9/9 i build PASS; Ruff/format/mypy/schematy/OpenAPI PASS. Migracja0010 zastosowana po backupie z zachowaniem wcześniejszych danych; zapis i decyzja przetrwały restart panelu. Test pg_dump/restore zachowuje dokument i historię oraz umożliwia kolejną rewizję. Niezależny QA bez pozostałych blokerów po poprawkach Unicode/integrity/NOWAIT. Brak nowych wywołań modeli. GPW, predykcje i wdrożenie VPS nadal wymagają kolejnych etapów.

- [x] P4-01c2a: trwała kolejka dokumentów, niezależny worker weryfikacji zapisanych szkiców offline, lease/heartbeat/fencing, odzyskiwanie, historia etapów i niezmienny audyt; panel zlecania i nadzoru. Tryb modelowy jawnie zablokowany przed wywołaniem dostawcy. [Zakres i odbiór](docs/DOCUMENT_TASKS.md).
- [ ] P4-01c2b: dopuścić operacyjne użycie modelu po kwalifikacji/polityce danych/budżecie i wdrożyć audyt faktycznych promptów, odpowiedzi, tokenów oraz kosztów; przyjmowanie samego dokumentu do ekstrakcji pozostaje do wykonania. Dotychczasowy audyt offline nie jest audytem wywołania LLM.
- [x] P4-01c2c: wspólny czytnik tekstowych PDF, lokalizatory stron, ograniczony proces Windows/Linux, archiwum i kolejka walidacji offline, wybór PDF w panelu i regenerowane kontrakty. [Zakres i ograniczenia](docs/PDF_READER.md). Brak OCR, nowych wywołań modeli i publikacji faktów.
- [x] P4-01c2d: podgląd dokumentu bez szkicuJSON i bez zapisu, wspólny czytnik/ustawienia, chroniony statelessendpoint i limity, panel z kontrolą hash/tożsamości i unieważnianiem spóźnionych wyników. [Użycie i odbiór](docs/DOCUMENT_PREVIEW.md). Archiwum nadal wymaga szkicu; model nie jest uruchamiany.

Odbiór podglądu2026-11-11:1464PythonPASS i1SKIP w końcowym pełnym przebiegu, panel61/61, Node9/9 i buildPASS; Linux19/19testówpodgląduPASS bezsieci/bazy/sekretów. Ruff/format/mypy/schematy/OpenAPIPASS. RzeczywistyPOST podglądu200 zezgodnymhashem iHTMLv2; liczniki archiwum/zadań/raportów bez zmian. /ready/panel/wcześniejszyGOOGL200 i3roleworkerów online. Końcowy przegląd koordynatora po wcześniejszym limicie podagenta; brak deklaracji wizualnego odbioru formularza. Bez migracji, modeli i nowych pobrań.

Odbiór PDF2026-11-10:1284PythonPASS w jednym końcowym przebiegu, panel53/53, Node9/9 i buildPASS; Ruff/format/mypy/schematy/OpenAPI/pipcheckPASS. NiezależnyQA bez pozostałych blokerów po poprawce rzeczywistego procesu timeout naWindows. Limity pamięci sprawdzone naWindows iLinux; lokalny panel i3rodzaje wykonawców działają, wcześniejszyGOOGL200. Archiwum i workerPDF sprawdzone na syntetycznych danych PostgreSQL. Bez migracji, nowych pobrańSEC, wywołań modeli i wdrożeniaOracle.

Odbiór kolejki dokumentów 2026-11-10: 1069 Python PASS, panel40/40, Node9/9 i buildPASS; Ruff/format/mypy/schematy/OpenAPI PASS. Migracja0011 po backupie, wcześniejsze dane zachowane. Zadanie utworzone przyciskiem przetrwało restart API i zakończyło się w osobnym procesie z audytem. Test odtworzenia kopii odzyskał przerwaną próbę jako kolejną, zachowując historię. Worker lokalny działa w tle, launcher nie duplikuje procesu. Niezależny QA bez pozostałych blokerów po poprawkach współbieżnego odczytu i odświeżania UI. Żadnych nowych wywołań modeli, publikacji metryk lub wdrożenia VPS.

- [x] P6-01b1: trwały rejestr sesji wykonawców SEC i dokumentów, heartbeat także bez zadań, rozpoznanie utraty kontaktu po45s, historia start/stop i read-only panel ze świeżością obserwacji. [Zakres i odbiór](docs/WORKER_SESSIONS.md).
- [x] P6-01b2: historia etapów importów SEC i scheduler z trwałymi potwierdzeniami, pauzą/wznowieniem, kontrolą rewizji, pomijaniem zaległości i zajętych instrumentów. [Zakres i odbiór](docs/SEC_SCHEDULES.md).
- [ ] P6-01c1: auth/TLS, supervisor i operacyjne wdrożenie VPS; scheduler lokalny nie zapewnia sam autostartu po restarcie systemu.
- [x] P6-01c1a: prywatny host HTTP z ochroną wszystkich ścieżek, TLS/Caddy, odrębny Compose i baza, plikowe sekrety, jawna migracja oraz lokalny odbiór. [Instrukcja i zakres](docs/PRIVATE_DEPLOYMENT.md). Regresja1248 Python PASS, panel53/53 i Node9/9; schematy/OpenAPI/Ruff/mypy PASS. Po poprawce cytowania healthchecku dodatkowy test konfiguracji2/2 PASS i rzeczywista gotowość kontenera. Bez wdrożenia VPS lub nowych wywołań modeli.
- [ ] P6-01c1b: instalacja na wskazanym VPS, autostart hosta, prywatny tunel i zaufanie CA po stronie operatora, kopia poza serwerem oraz próbne odtworzenie na docelowej infrastrukturze.

Odbiór rejestru wykonawców2026-11-10:1110PythonPASS w jednym pełnym przebiegu, panel46/46, Node9/9 i buildPASS; Ruff/format/mypy/schematy/OpenAPIPASS. Migracja0012 po backupie i kontrola zachowania danych. Dwa rzeczywiste workery odnawiają heartbeat bez nowych zadań; próby normalnego i nagłego zakończenia wykazały stopped oraz stale. Odtworzenie kopii zachowuje historię sesji. Odbiór wizualny potwierdził wygaszanie aktualności po pauzie i nowy stan po wznowieniu. Końcowy przegląd przeprowadził koordynator; niezależne QA podagenta nieukończone wskutek limitu użycia. Bez nowych wywołań modeli i wdrożenia VPS.

Odbiór historiiSEC i schedulera2026-11-10:1153PythonPASS w jednym pełnym przebiegu, panel53/53, Node9/9 i buildPASS; Ruff/format/mypy/schematy/OpenAPIPASS. Migracje0013/0014 po backupie z zachowaniem wcześniejszych danych; starsze zadanie ma jawny legacy_snapshot. Test odtworzenia kopii zachowuje harmonogram, potwierdzenia i historię bez powtórnego dispatchu. Niezależny QA bez pozostałych P1/P2 po ograniczeniu odczytu historii. Scheduler działa z pustą konfiguracją; spółki i terminy wybiera użytkownik. Trzy procesy mają aktualne heartbeat. Bez nowych pobrań SEC i wywołań modeli podczas odbioru; VPS nie wdrożono.


Odbiór AI z historią2026-11-12:1617PythonPASS/1SKIP w pełnym przebiegu PostgreSQL, panel89/89, Node9/9 i buildPASS; Ruff/format179plików, mypy82modułów, schematy/OpenAPI i pipcheckPASS. NiezależnyQA4scenariuszy oraz2rzeczywistych analizPASS z ograniczeniami jakości opisanymi w docs/AI_HISTORY_ANALYSIS.md. Migracja0016 po backupie zachowała stare raporty/AI/audyt/limit. GOOGL/AAPL v1 i v2 oraz38PLN pozostałej rezerwy przetrwały restart; zapisano nową kopię PostgreSQL. Walidator panelu potwierdził rzeczywisteSHA-256 obu wersji, interfejs pokazał nową analizęGOOGL i dowody trendu; trzy roleworkerów online.6wywołań w etapie, bez nowych pobrańSEC i bez wdrożeniaVPS.


Odbiór wskaźników2026-11-12:1649PythonPASS/1SKIP w pełnej regresji PostgreSQL; osobno końcowe42testy wskaźników/API PASS, w tym10przypadków dodanych po kolekcji pełnego przebiegu. Panel98/98, Node9/9, build/Ruff/format/mypy84modułów/schematy/OpenAPI/pipcheckPASS. NiezależnyQA bez blokerów; rzeczywisteGOOGL3wyniki+9braków, AAPL12wyników, walidator frontendowy i UI dowodówPASS. Poprzednie raporty/AIhashy/budżet38PLN i podpisana implementacjaAI niezmienione po restarcie panelu. Bez migracji, nowych źródeł, modelcalls i wdrożeniaVPS.

Odbiór wykresów2026-11-12:106/106testów panelu, w tym8nowych przypadków geometrii/braków/precyzji, Node9/9, TypeScript/Vite i schematy/OpenAPIPASS. NiezależnyQA bez blokerów, dodatkowe próby wartości skrajnych/gap/immutabilityPASS. UI potwierdził rzeczywisteGOOGL, wybór punktu Enter, dokładną wartość, reset szczegółów po zmianie metryki i jawny brak danych przepływowych. Kontrola raportów/AIhashy i budżetu38PLN bez zmian; sygnaturaAI/history zgodna. Brak nowego przebieguPython — kodbackendu niezmieniony.
