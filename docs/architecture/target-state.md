# Stan docelowy — zaakceptowany kierunek

Data kierunku: 2026-10-30; aktualizacja planu: 2026-11-02. Kierunek zatwierdzony w [ADR-0001](../adr/0001-platform-architecture.md). To opis celu, nie całego wdrożenia. Python obejmuje walidację, trwałe raporty/rejestr/snapshoty oraz lokalny worker deterministyczny; szczegóły w [BACKEND](../BACKEND.md) i [AUTOMATIC_WORKER](../AUTOMATIC_WORKER.md). Kronos i jego hosting pozostają planem.

## Ograniczenia obowiązujące już teraz

Wyłącznie darmowe źródła i brak płatnych fallbacków. Wzmianki o płatnych providerach, rezerwach i zwiększeniu limitów w starszej dokumentacji/config oraz audycie nie upoważniają do ich aktywowania. Brak darmowego dostępu, nieznany koszt, wyczerpana kwota lub niezweryfikowana licencja mają kończyć etap jako partial/blocked, bez dopłaty i bez podmiany na syntetyczne dane. Darmowy dostęp nie dowodzi prawa do redystrybucji ani dostępności historii PIT.

Pierwszy przyrost działa bez LLM. Lokalne modele również wymagają pomiaru zasobów i polityki danych; nie zakładamy zerowego kosztu obliczeń. Research-only: bez brokera, zleceń i automatycznego wykonywania kodu LLM. Zachować pliki, raporty i lokalne zmiany użytkownika.

## Architektura rekomendowana

Python 3.12+, FastAPI/Pydantic v2 jako docelowy modularny backend; React/TypeScript/Vite jako docelowa PWA. PostgreSQL/SQLAlchemy/Alembic dla stanu i migracji, magazyn obiektów dla wersji danych/raportów, Parquet/DuckDB dla historii. Obecny lokalny worker korzysta z kolejki PostgreSQL. Redis/Celery tylko po wykazaniu potrzeby; pozostała infrastruktura wymaga pomiaru kosztów, bez automatycznego zakupu hostingu.

Node M0 pozostaje uruchamialnym demonstratorem, punktem odniesienia i źródłem syntetycznych przypadków odbioru. Nie rozwijamy dwóch docelowych silników analitycznych. Statyczna PWA pozostaje do czasu jawnego przełączenia na React. Nie zmieniamy istniejących ścieżek przy samym discovery.

## Granice danych i kontraktów

Przed implementacją uzgodnić wersjonowane wejścia/wyjścia. Schematy mają rozdzielać pochodzenie synthetic/live od kompletności, a brak od zera. Każda obserwacja wymaga jednostki, waluty gdy dotyczy, okresu, źródła/snapshotu oraz udowodnionego available_at. as_of jest czasem odcięcia; event_time, published_at i ingested_at nie są zamienne. Nie wyprowadzać historycznej dostępności z samego filed ani bieżącego first_seen.

Jedna definicja kontraktu, walidacja 2020-12 wraz z date-time na granicach i zgodność z Pydantic/OpenAPI. Mapowanie legacy report do nowej wersji jest jawne; nie przepisywać istniejących raportów. Kontrakty publicznego API v1 wymagają testów i generowanego klienta TypeScript. Analityka jest deterministyczna, narracja LLM opcjonalna i odseparowana od narzędzi wykonawczych.

## Pierwszy rzeczywisty pionowy przyrost

Po przeglądzie ADR: kontrakty i fixture → szkielet FastAPI → adapter fundamentów → raw snapshot/hash → obliczenia → raport partial JSON/HTML bez cen i LLM. SEC jest kandydatem z wcześniejszego audytu, nie aktywnym lub ponownie zweryfikowanym źródłem. Warunki, limity, kontakt i dostęp sieciowy muszą być sprawdzone w osobnym zadaniu przed aktywacją. Alpha Vantage i EIA pozostają tylko historycznymi kandydatami; brak założonych kluczy, uprawnień czy aktualnych limitów. Płatna rezerwa Sharadar z audytu jest wykluczona.

Ceny EOD i corporate actions wymagają osobnego zatwierdzenia darmowego źródła. Bez nich technika rzeczywistych cen i backtest pozostają niedostępne. PDF, scheduler, powiadomienia, auth i produkcja to dalsze etapy z własnymi kryteriami odbioru, nie cechy pilota; lokalna kolejka deterministycznego workera nie realizuje całego tego zakresu.

## Opcjonalny moduł Kronosa i hosting — plan 2026-11-02

Przyjąć do planu funkcję „Scenariusze cenowe”: osobny asynchroniczny worker modelu, zamrożone świece EOD, wersjonowany artefakt prognozy i cache. Model nie pracuje w procesie API ani nie zastępuje deterministycznej techniki/fundamentów. Pilot: jeden rynek equity/ETF, horyzonty 5/20 sesji, mini/small porównane lokalnie, jeden model po kwalifikacji, bez fine-tuningu. Kontrakty prognoz są do zaprojektowania; obecny raport v1 nie dopuszcza niepustego model_provenance ani wykresów.

Kolejność: darmowe źródło i polityka danych → kontrakty i fixture → benchmark zasobów → walk-forward/OOS z kontrolą okresu pretrainingu → worker z cache → UI i raport → hosting. Włączenie dopiero po ustalonych z góry progach jakości i zasobów; brak poprawy nad baseline oznacza pozostawienie eksperymentu wyłączonego. Brakujące wejścia blokować, nie uzupełniać zerami upstream.

Start lokalny. Hosting aplikacji oddzielić od obliczeń: serwer CPU po benchmarku albo serwer aplikacji z prywatnym dostępem do lokalnego workera; GPU dopiero po wykazaniu potrzeby i dopuszczeniu kosztu. Zdalne pobieranie zadań wymaga osobnego bezpiecznego rozwiązania, nie publicznego PostgreSQL. Bez wybranego dostawcy, zakupów i obietnicy 24/7.

Pełne granice kontraktów, bramki i warianty operacyjne: [Kronos — scenariusze i hosting](kronos-scenarios.md). Kolejność i odbiór: [roadmap KR-00–KR-06](../roadmap/issues.md#kronos--opcjonalne-scenariusze-cenowe-2026-11-02).
