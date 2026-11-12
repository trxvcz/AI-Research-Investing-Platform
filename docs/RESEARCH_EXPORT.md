# Eksport gotowej analizy

Panel otrzymuje dwa warianty pliku: HTML do czytania bez uruchomionej aplikacji oraz JSON do dalszego przetwarzania. W sekcji AI eksport przypisuje dokładnie wybraną zapisaną analizę, również wcześniejszą wersję. Osobne linki przy raporcie eksportują dane bez narracjiAI. Pobranie nie zleca nowej generacji.

Plik zawiera identyfikację i stan raportu, as_of, historię roczną, wskaźniki, źródła i ograniczenia. WariantAI dodatkowo obejmuje model, wersję instrukcji, UUID i czas zapisanego wyniku oraz cytowania. Cytowania v2 odnoszą się do niezmiennego kontekstu tamtej analizy, a nie indeksów bieżącej tabeli. Wariantv1 zachowuje pierwotny zakres obserwacji. Nie eksportujemy prywatnego audytu prompt/raw ani konfiguracji i sekretów.

Eksport JSON jest wersjonowany `research-export-v1` i ma deterministyczny SHA-256 zawartości. Suma kontrolna wykrywa zmianę danych; nie jest podpisem potwierdzającym autora. Brak automatycznego wyboru najnowszegoAI po stronieAPI. Nieistniejący identyfikator, inny raport lub niedokończona analiza dają odmowę zamiast zamiennego wyniku.

HTML jest statyczny, bezJavaScript i zasobówzewnętrznych. Tabele i treść czyta się offline; otwarcie linku doSEC wymaga internetu. W tym przyroście eksport zawiera dokładne tabele, bez interaktywnych wykresów iPDF. Teksty źródeł są escapowane; klikalne linki ograniczono do zatwierdzonych adresów HTTPSSEC.

API: GET `/v1/panel/reports/{report_id}/{revision}/research-export` oraz `/research-export/html`; opcjonalny `ai_request_id`. Odpowiedzi mają attachment, no-store i nosniff. Żaden endpoint eksportu nie uruchamia modelu lub pobierania źródeł. Wygaśnięcie przegląduAI i wyczerpanie budżetu nie blokują odczytu istniejącego wyniku. Działanie wymaga dostępnych archiwów raportu; nie tworzymy niepełnego zastępczego eksportu przy awarii bazy.

To dokument badawczy, bez wyceny, prognozy kursu i rekomendacji. Komparatywy mogą być przekształcone i nie odtwarzają wiedzy inwestora w dawnym roku. GPW, automatyczna ekstrakcja dokumentów i hostingVPS nadal wymagają odrębnych etapów.

Odbiór rzeczywisty2026-11-12: GOOGL i AAPL, każda w warianciev1/v2 oraz bezAI; cztery wybrane eksporty AI zwalidowano modelem, powtórne żądania dały identyczne bajtyJSON. Potwierdzono attachment/no-store/nosniff/CSP, brak skryptów i zapisane sumy kontrolne. Raporty, stare/noweAIhashy i38PLN rezerwy pozostały niezmienione.

W panelu potwierdzono linki do dokładnie wybranej wersjiAI; samodzielny HTML Apple otwarto osobno i sprawdzono tekst oraz wygląd. Tabele zachowują dokładne wartości; identyfikacja zawiera instrumentUUID bez zgadywania nazwy emitenta. Wartości i daty są obecnie zapisane technicznie, bez skracania kwot.

Testy eksportu42/42PASS; panel106/106, Node9/9, TypeScript/Vite, Ruff/format, mypy87modułów, schematy/OpenAPI i pipcheckPASS. Pełna regresja PostgreSQL:1701PASS/1SKIP (brak symlinkówWindows),489.75s. NiezależnyQA przejrzał model/API i wskazał poprawione wiązanie źródeł oraz kompletność obserwacjiHTML. Podagenci osiągnęli limit przed końcowym podpisaniem całości; końcowy przegląd bezpieczeństwa i odbiór wykonał koordynator. Bez nowych zależności, migracji i wdrożeniaVPS.
