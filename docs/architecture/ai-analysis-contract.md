# Gotowa analiza AI — kontrakt przyrostu 2026-11-11

Właściciel dopuścił Gemini Paid i limit50PLN. Interpretacja bezpieczna:50PLN łącznie, bez odnowienia. Potwierdził, że obecny klucz.env jest Paid/Tier1. To osobna, jawna zgoda; FreeOnlyGateway i polityka darmowych źródeł pozostają bez zmian. Nie włączać ogólnego płatnego fallbacku.

Produkt: przy istniejącym raporcie użytkownik wybiera „Generuj analizę AI”. Otrzymuje polskie podsumowanie, mocne strony, ryzyka, kwestie do sprawdzenia i odwołania do obserwacji. Brakujące dane jawne; bez kup/sprzedaj, ceny docelowej i wymyślonych predykcji. Wszystkie obsługiwane spółki używają tego samego silnika. Pierwszy zakres to zapisane raporty; pozyskanieGPW pozostaje osobnym etapem.

## Wspólne kontrakty i własność

Koordynator: ai_analysis_contracts.py, ai_analysis.py, ai_analysis_api.py, integracja API/schematów, konfiguracja i dokumentacja. Backend: ai_analysis_store.py, migracja0015_ai_analysis i tabele wdb_schema.py, własne testy. Frontend: ai-analysis.tsx, ai-analysis-state.ts, integracja main.tsx, własne testy. QA niezależny po integracji.

AiAnalysisCreate: request_idUUID, report_idUUID, revisionint>=1. API POST /v1/panel/ai-analyses, te same Origin/auth/JSON co inne mutacje, body<=4096. GET /v1/panel/ai-analyses/{request_id}; GET /v1/panel/ai-analyses?report_id=UUID&revision=int zwraca listę maks20 najnowszych, bezprompt/raw. GET /v1/panel/ai-budget zwraca budget_pln='50.00',reserved_pln decimalstring,remaining_pln decimalstring, reservation_per_attempt_pln='1.00', enabledbool,reasonstr|null. Brakautomatycznych generacji przy odczycie.

Wynik publiczny AiAnalysisRecord: request_id,report_id,revision,report_checksum, status running/completed/failed,created_at,finished_at|null,model_id,prompt_version='report-synthesis-v1',analysis(AiNarrative|null),error_code|null,reserved_pln='1.00'. AiNarrative: summary(list[AiClaim]1..6), strengths/risks/questions(list[AiClaim]0..6), limitations(list[str]1..12). AiClaim: textstr1..1200,observation_indexes(list[int]1..20unique). Narracja nie zawieraHTML aniURL; frontendrenderujeReacttext. Indeksy muszą wskazywać dostępne obserwacje raportu. Odpowiedź narzędzi/nieznanyklucz/niedomknięteSTOP/niepoprawnecytowanie jest odrzucana wcałości. Walidacja cytowań nie dowodzi prawdziwości interpretacji; AI jest jawnie opisana jako interpretacja wymagająca sprawdzenia.

## Trwały limit i idempotencja — interfejs store

AiAnalysisStore(engine).reserve(request_id:UUID,report:ReportRevision,model_id:str)->bool: transakcjaadvisorylock globalnego scope'ai-analysis-pilot-20261111', następnie istniejącyrequestid dokładnieporównany doreport_id/revision/checksum/model; zwracaFalse dlaistniejącego,True dlazarezerwowanegonowego. Limit5000groszy, rezerwacja100groszy, bezrefundów. Nawetfailed/running po restarciezużywa rezerwację. Idempotentnyten samrequest nie generujeponownie. Niepewneprzerwanie pozostajerunning i wymagaodczytu, nie przejęciapróby.

Store.get(request_id)->AiAnalysisRecord|None; Store.list(report_id,revision)->list[AiAnalysisRecord]; Store.budget()->dict zpolami jakAPI (enabled/reason ustawiaAPI); Store.finish(request_id,analysis:AiNarrative|None,error_code:str|None,audit:dict)->AiAnalysisRecord: tylkojednorazowyUPDATE running->terminal, finish możeudostępniaćtylkokoordynator. Auditprywatny JSON obejmujeinput/prompt/rawresponse/hash,usage lubnull,modele,czasy i kosztrezerwacji. NieudostępniaćgoAPIGET.

Store wyjątki: AiBudgetExceeded, AiRequestConflict, AiStoreUnavailable. PKrequest_id,FKrevision_id do report_revisions; rekord wiążez dokładnąrewizją. Baza wymuszaterminalność oraz niezmiennośćtożsamości/audytu terminalnego, blokadęDELETE/TRUNCATE (jakistniejącetabele). Niezerowaćbudgetu przyrestarcie. KontrolaMIGRATION_HEAD0015, aktualizacja migrationtests i restoretests należy dointegratora.

## Wywołanie i dopuszczenie

Gemini gemini-3.1-flash-lite Standard, braktools/cache/grounding/retry/fallback. maxOutputTokens2048, temp0. Request JSON maks32768bajtów (wejście: tylko znormalizowane dane i ichźródła; bezsurowychdokumentów/sekretów/notatekużytkownika). Produkcyjnie tylko report.input.data_origin='live' i źródłaSEC zhttpswww.sec.gov/data.sec.gov. Test syntetyczny wyłącznie osobnymCLI kwalifikacyjnym. Hasheklucza oraz oficjalnychcen/warunków i Paid ownerconfirmation w prywatnym plikuaktywacji. Ceny Standard odczytane2026-11-11:0.25USD/Minput i1.50USD/Moutput; zachowajdowód. Konserwatywnabound: input<=32768UTF8bytes+10000tokenówmarginesu, output<=2048tokens, przelicznik10PLN/USD i2xmargin; poniżej1PLNrezerwacji. To aplikacyjny limit rezerwacji: nie kontroluje wywołań klucza pozaaplikacją ani rachunkuGoogle/podatków. Brakujęcego usage nie zamieniaćwzero. Brak aktywacji lub niezgodnyhashkey/przeterminowanyprzeglądblokuje przedrezerwacją/siecią.

Przed aktywacją: testydeterministyczne, 3zamrożoneprzypadki syntetyczne narracji (wtymbrakdanych i promptinjection wetykiecieźródła), ręcznaprzeglądowalnaocenaPolish/cytowania/braknowychfaktów/abstencjibrakującychdanych. Wywołaniakwalifikacji teżrezerwują1PLNwtymsamymbudżecie (oddzielnekwalifikacyjneUUID/reportsynthetic w testowymrejestrzequota; storeglobalniezliczałącznie, implementacjakoordynatora). Jeśli niespełnione, providerwyłączony, publikowanawynikupomiaru. Popowodzeniu jednapróbanapublicznychdanych istniejącegoGOOGL jako pilot, zapis i UIodbiór. Dalszegeneracjetylkojawnyklik, bezzaplanowanychpłatnychzadań.

Zapisaneanalizy bezponownejopłaty, rozdzieloneod niezmiennychdeterministycznychraportów1.0. Niezmieniamyhistorycznychchecksum/treści.
