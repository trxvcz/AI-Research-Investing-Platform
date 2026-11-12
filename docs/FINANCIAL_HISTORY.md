Aktualizacja2026-11-12: nowe analizy AI korzystają z przypisanych okresów przez osobny, niezmienny kontekst. Starsze narracje zachowują poprzedni zakres. [Bieżąca integracja](AI_HISTORY_ANALYSIS.md). Poniższy odbiór tabeli opisuje poprzedni etap.

# Wyniki na przestrzeni lat

W panelu pod analizą AI dostępne są roczne dane porównawcze z maksymalnie trzech okresów sprawozdawczych oraz obliczona zmiana r/r. Otwórz GOOGL lub AAPL i przejdź do **Wyniki na przestrzeni lat**. Przycisk odświeżenia ponawia tylko lokalny odczyt; nie pobiera SEC i nie uruchamia Gemini.

## Wdrożony zakres

- Przychód, wynik netto, przepływy operacyjne i nakłady inwestycyjne, jeśli raport ma dostępną obserwację wUSD i jej oryginał w archiwum.
- Maksymalnie trzy najnowsze okresy z tego samego sprawozdania co wybrany raport. Obsługa roku kalendarzowego i przesuniętego roku obrotowego, bez reguł zależnych od symbolu spółki.
- Dokładne wartości i zmiany kwotowe jako tekst dziesiętny; r/r z sześcioma miejscami, ROUND_HALF_EVEN. Frontend sprawdza arytmetykę i formatuje wartości BigInt bez utraty cyfr.
- Link do źródła, dostępność oryginału, data złożenia, accession i hash. Historia związana z konkretnym report_id/revision/checksum orazas_of.

Przykłady odbioru z istniejących archiwów: GOOGL ma2serie po3okresy2023–2025; Apple4serie po3okresy obrotowe kończące się wewrześniu2023–2025. Zmiany obliczono na zapisanych oryginałach. Ich odczyt nie zmienił raportów ani narracjiAI, a budżet pozostał44PLN.

## Co oznaczają porównania

Companyconcept zawiera fakty z wielu publikacji i jednostek, co opisuje [dokumentacja SEC](https://www.sec.gov/search-filings/edgar-application-programming-interfaces). Nasza metoda wybiera jeden accession i filingdate zgodny z bieżącą obserwacją raportu, odcina późniejsze publikacje względem jejevent_time i nie miesza przekształconych wersji z różnych sprawozdań. Przykładowo źródła przepływów Apple zawierają także późniejszą wersję poprzedniego roku; nie zastępujemy nią publikacji wybranej w raporcie.

**Dane porównawcze z tego samego sprawozdania mogą zawierać przekształcenia. Nie jest to odtworzenie wiedzy inwestora w dawnym roku.** available_at pozostaje datą dostępności użytego archiwum, nie datą historycznego okresu. Widok nie odświeża danych raportu do najnowszego roku dostępnego dziś naSEC.

Zmiana r/r wymaga dwóch kolejnych, ciągłych rocznych okresów. Różnica ich długości może wynosić najwyżej8dni, co obejmuje typowy układ52/53tygodni. Zmiana roku obrotowego, luka lub nieporównywalny okres powodują odmowę obliczenia zmiany. Przy zerowej lub ujemnej bazie pokazujemy różnicę kwotową, bez procentu. Najstarszy punkt nie dostaje wyliczonej zmiany. Nie zastępujemy braków zerem.

Niejasne accession, sprzeczne duplikaty, nakładające się okresy, niewłaściwe jednostki lub rozbieżności pochodzenia powodują jawne oznaczenie serii jako niedostępnej. Uszkodzone albo niedostępne archiwum nie jest pustym prawidłowym wynikiem. Parser ma limit bajtów i ogranicza cyfry/wykładniki przed rozwijaniemDecimal, aby krótka złośliwa liczba nie powodowała nadmiernej alokacji pamięci.

## Relacja do AI

**Generowanie narracji AI nie korzysta jeszcze z nowych okresów porównawczych.** To osobny widok obliczeń. Dotychczasowe analizy AI i ich audyty pozostają niezmienne; ponowne kliknięcie generacji w tym etapie nie włącza historii do promptu. Następny przyrost wymaga nowej wersji kontekstu dowodów, powiązania indeksów cytowań z historią, kwalifikacji i zachowania wspólnego limitu50PLN. Ten etap nie zużył kolejnych rezerwacji.

## API i odbiór

GET `/v1/panel/reports/{report_id}/{revision}/financial-history`, bez mutacji i zno-store. JSONSchema: financial-history. Metoda sec-comparatives-v1. Oryginały pochodzą wyłącznie z snapshotów wskazanych w raporcie, kontrolowane są bajty, hash, tożsamość instrumentu, URL/CIK/tag i daty. Nie ma migracji, nowych zależności, zmian polityk źródeł/modeli lub wdrożeniaOracle.

Pełna regresja: **1555PythonPASS,1SKIP** (symlinki niedostępne na tym hościeWindows), w tym37testów parsera i4nowegoAPI. NiezależnyQA potwierdził poprawkę jednostek rzeczywistych raportów i brak pozostałych blokerów. Panel83/83, Node9/9 i buildPASS; Ruff/format/mypy/schematy/OpenAPI/pipcheckPASS. RzeczywistyHTTP200 daje2serie GOOGL i4Apple po3okresy; ten sam wynik zaakceptował walidatorfrontendowy. Odbiór interfejsu potwierdził tabelę GOOGL2023–2025, zmianyr/r, źródła i ostrzeżenie o braku integracji zAI. Porównanie stanu bazy potwierdza niezmienność raportów/narracjiAI oraz44PLN rezerwy. Bez migracji, nowych pobrań źródeł i generacji modeli.
