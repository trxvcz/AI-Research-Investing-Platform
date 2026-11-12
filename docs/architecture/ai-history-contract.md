# AI z historią — P4-02d2, 2026-11-11

Właściciel zlecił kolejny etap: narracja wykorzystująca okresy porównawcze. Zgoda GeminiPaid50PLNłącznie bez odnowienia pozostaje; na starcie44PLN pozostało. Rezerwacja1PLN przed każdą próbą, także kwalifikacją; bezrefundów/retry/fallbacku. Źródła tylko zapisane publiczneSEC, bez nowych pobrań. Nie zmieniaj dawnych raportów/narracjiAI. Nowy prompt_version='report-history-v2'. Dotychczasowy 'report-synthesis-v1' pozostaje czytelny, bez automatycznego przenoszenia indeksów.

## Własność i moduły

ContextBackend: ai_history_context.py,ai_history_contracts.py,test_ai_history_context.py. StoreBackend: ai_analysis_store.py,ai_analysis_contracts.py,db_schema.py,migracja0016_ai_history_context,test_ai_analysis_store.py. Frontend: ai-analysis.tsx,ai-analysis-state.ts,ai-history-context.ts,nowetesty oraz tekstfinancial-history.tsx. Koordynator: ai_history_analysis.py,ai_analysis_api.py,health/schema/APIintegration,kwalifikacja i docs. QA po zwolnieniu slotu. Nie zmieniaj ai_analysis.py/AiClaim/AiNarrative: zachowujemy dowód i odtwarzaniev1.

## Kontekst i DTO (ContextBackend)

AiHistoryContext: context_version='report-history-context-v1',report_idUUID,revision>=1,report_checksum,as_of,methodology_version='sec-comparatives-v1',evidence(list[discriminatedunion fact/comparison]1..64),limitations(list[str]1..16),context_sha256. Canonicalhash jak canonical_sha256JSON z wyłączeniem context_sha256. Indeksy indexint0..63 są gęste i stabilne. Rewaliduj zmodel_dump na granicy i sprawdzajhash, czasy oraz referencje.

AiHistoryFact: kind='fact',index,metric,unit,currency|null,value dokładnydecimalstring<=128znaków,period_start/endTimestamp,available_atTimestamp,source:SourceProvenance,report_observation_index int|null,filing_accession str|null. Dla oryginalnych dostępnych obserwacji konwertujvalue przezDecimal(str(float)) bez utraty reprezentacji raportu i zachowaj report_observation_index; bez brakujących obserwacji. Dla wcześniejszych okresów z FinancialHistorySeries dokładnevalue,sourcepowiązanezraportem,available_atzarchiwum; report_observation_index=null. Te samevalue/metric/period/source snapshot nie duplikują bieżącego punktu. Nie łącz różnych wersji/snapshotów tylko dlatego, że wartości są identyczne.

AiHistoryComparison: kind='comparison',index,metric,previous_index,current_index,delta_value decimalstring|null,delta_percent decimalstring6|null,comparison_reason null/'NON_POSITIVE_BASE'/'PERIODS_NOT_COMPARABLE'. Powiązania wskazują wcześniejsze elementyfact otej samejmetryce/walucie/jednostce i pochodzące z tej samej serii; obliczenia niezależniezweryfikowane jak FinancialHistory. Nie twórz porównania 'NO_PRIOR_PERIOD'. Dla okresów nieporównywalnych obiedeltanull; nie używajgotrendclaims. Przy niedodatniejbazie deltakwotowa, procentnull. Dostępnośćobu<=as_of. Zachowaj nieporównywalność jako dane, nie omijajjej wyboru innychlat.

build_history_context(report:ReportRevision, history:FinancialHistory)->AiHistoryContext: sprawdza dokładnątożsamośćraportu/as_of/sourcehashy/sourceURL/anchor(currenthistorypoint==dostępnaobserwacjaperiod/value/metric/snapshot) oraz arytmetykęhistorii. Nie ufa mutowalnemu/spreparowanemuhistory. Oryginalnefaktywpierwszejkolejności w kolejnościinput.observations; poprzednielata w kolejnościsiecihistoryseries i okresów; porównaniana końcu. Wynikniezależny odkolejnościinputhistoryseries (sortujmetrykąstabilnie). Braktruehistorii jestjawnąlimitations, nieblokujnarracjijednookresowej.

AiHistoryClaim: kind='state'/'trend'/'question',text1..1200,evidence_indexes(list[int]1..20unique),direction(null/'increase'/'decrease'/'unchanged'). AiHistoryNarrative: summary1..6, strengths/risks/questions0..6,limitations1..12,układ jakv1,leczclaimsnowetypy. validate_history_narrative(context,raw_json)->AiHistoryNarrative: stricteJSON/schema/rozmiar, brak cyfr/HTML/URL/zaleceńkup/sprzedaj, wszystkieindeksyistnieją; kindstate cytujefacty i directionnull; kindtrend cytujedokładnie1comparisonporównywalnyzdeltąkwotową, kierunekrównysign(delta); kindquestion directionnull icytatyistnieją. Wsekcjiquestions wszystkiekindquestion,pozostałekindstate/trend. Cytowania/arithmeticnieudowadniająsemantyki tekstu: potrzebnybenchmark/ręcznyQA.

validate_history_context(context, report:ReportRevision|None=None)->AiHistoryContext: pełnaspójnośćwewnętrzna/hash; gdyreportpodany: identity/asof,originalfactexactbinding i wszystkiesourceszreportu. Potrzebnewstore.finish iAPI. Wyjątek AiHistoryInvalid.code. Modele/konstruktor/validator wmodułachContextBackend (kontrakty i funkcje uzgodnij lokalnie; eksportujnazwyopisane).

## Trwałość (StoreBackend)

AiAnalysisRecord.prompt_version literalv1/v2,analysis union AiNarrative/AiHistoryNarrative|null,evidence_context AiHistoryContext|null domyślnieNone i exclude_ifNone (v1 JSON beznowegopola). Walidator wymuszapoprawnytypnarracji+kontekst v2, v1 braknowegokontekstu, tożsamośćchecksum/id/revision; v2completedcytowaniawalidowaneprzezvalidate_history_narrative przyodczyciebezwywołaniaLLM. Running/failedv2teżmajązamrożonykontekst.

AiAnalysisStore.reserve(request_id,report,model_id,*,prompt_version='report-synthesis-v1',evidence_context:AiHistoryContext|None=None)->bool. Stareregresjedomyślnev1. Nowe v2 wymagająkontekstuvalidate_history_context(context,report) przedrezerwacją; identyczneUUIDporównujmodel/prompt/contextsha, innykontekstkonflikt. BieżącaAPIoddajeistniejącyrequest zanimodtworzyhistorię. finish akceptujeunionnarracji, używazamrożonegokontekstuzrekordu dla v2; nieindeksuje go względemstaregoreport.input. NiezmiennośćcontextodINSERT i terminalnejaudit. Prywatnyauditobejmujekonteksthash i prompt/raw takjakv1. Publicznycontextniezawierasekretów,surowychdokumentówlubnagłówków.

Migracja0016: nowakolumnaai_analyses.evidence_contextJSONB, promptconstraintv1/v2, checkv1contextnull/v2object identity/reportchecksum, maks256KiB JSONtext; aktualizacjatriggera uniemożliwiazamianęcontext i zachowujeledger/budget. MIGRATION_HEAD0016. Bezresetubudżetu. Downgraderefusegdyistniejev2. Starewpisy i odpowiedziv1 niezmienne. Testy PG:roundtripv2/pastrefs/badcontext/unknownindex/conflict/immutablecontext/budget/backuprestoreold+new.

## Engine i API (koordynator)

Oddzielny ai_history_analysis.py zmodelemtym samym,limitemrequest32768B/output2048tokenów/1PLNrezerwy. Nowakonfiguracjaprywatnaprompt_versionv2 i sygnaturakodu+kontraktów+buildera kontekstu+parserahistorii. Brak aktywacji dopóki nowykwalifikacyjny pomiar nieprzejdzie. Nie podrabiajqualitypass. Ceny/warunkiponowniesprawdzone,kluczniezmieniony i właścicielPaidpotwierdzony wcześniej. WAPIcheckbudget/health używajnowejaktywacji; starycorenieaktywujfallbackiem.

POST /v1/panel/ai-analyses ztym samymAiAnalysisCreate dla NOWEGOrequest tworzyv2. Istniejącerequestyv1/v2odtwarzabeznowegowywołania. APIzaufanieskładaSnapshotStore.content zraportu -> build_financial_history ->build_history_context ->prompt ->commitreserve ->1transport ->validate ->finish. Nigdy niezwracajkontekstunadesłanegoprzezklienta. GETlist/get obsługująobiewersje. Brak automatycznych płatnychzadań. Przedłużenieprzegląducen/warunków nieodnawialimitu.

## Frontend

Waliduj v1 po staremu. V2 obowiązkowycontext hash/reportidrevisionchecksum/as_of/available_at/sources i gęsteindeksy. Claims cytująevidence_indexes; trendpokazuje poprzednią/bieżącąwartość, okresy, zmianę i źródła z zamrożonegokontekstu. StanbieżącyhistoryAPI nie możeprzepisywaćcytowańzapisanejnarracji. NatywneReacttext, brakrawHTML. Przyv1etykieta'Analiza wcześniejsza — bez historii', przyv2'Analiza z historią'. Nowageneracjajawnyklik, UUIDi niepewneponowieniezachowane. Ostrzeżenie zakresudługu nadalwidoczne. Teksthistorycomponentmówi, żenoweAIużywaprzypisanegokontekstu,astareanalizyniezmienione.

## Odbiór

Najpierw deterministyczne testy i backup/migracja. Zamrożony pilot4przypadków: dodatnitrend, niedodatniabaza bezprocentu, nieporównywalneokresy/nieufnaetykieta, zakresdwóchczęścidługuniebędącychcałymizobowiązaniami. Rezerwacjeztesamego50PLN. Stoprunpopierwszymbłędzie, bezretry. Wramachtegoetapu maks8płatnychprób (kwalifikacja,2rzeczywisteraporty,ewentualnanowazamrożonawersjapopoprawce),bezzużyciaresztylimitudodiagnostyki. RęcznyQAporównujesemantykę icytowania,nieJSONtylko. Poprzejściu2rzeczywisteanalizyGOOGL/AAPL jako noweUUID; starewpisy zachowane. Pełnaregresja,npmtest,schematy,przeglądbezpieczeństwa,restart/odtworzenie i TASKS/docs.
