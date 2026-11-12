# Dopuszczenie źródła SEC — 2026-11-02

Zakres: lokalny research z publicznych submissions i companyconcept/us-gaap. Nie dotyczy API składania zgłoszeń, zewnętrznych agregatorów, brokerów ani modeli. Zatwierdzono jeden wpis `sec-edgar-public-v1` w polityce serwera.

## Oficjalne podstawy przeglądu

- [EDGAR APIs](https://www.sec.gov/search-filings/edgar-application-programming-interfaces): publiczne JSON na data.sec.gov, bez uwierzytelnienia i klucza; osobne submissions i companyconcept. Wniosek dla tego adaptera: anonimowy GET nie wymaga rachunku ani mechanizmu naliczania opłat. Nie przenosimy tego wniosku na usługi innych dostawców.
- [Developer Resources](https://www.sec.gov/about/developer-resources) oraz [Accessing EDGAR Data](https://www.sec.gov/search-filings/edgar-search-assistance/accessing-edgar-data): efektywny, identyfikowany dostęp i maksymalnie10 zapytań/s łącznie dla użytkownika. Pilot ograniczono do jednego aktywnego zapytania z dodatkową przerwą1s.
- [SEC Privacy / Website Dissemination](https://www.sec.gov/about/privacy-information): SEC opisuje informacje na swojej stronie jako publiczne, dopuszcza kopiowanie z odpowiednim wskazaniem źródła i zastrzega odrębnie logo/znaki. Pilot podaje źródła tekstowo, nie używa logo i nie sugeruje powiązania z SEC. Pole license wskazuje tę politykę; nie przypisano wymyślonej licencji CC0.

Zapis dokładnych bajtów strony privacy-information: 90414 bajtów, pobrano `2026-11-02T11:23:44.562035Z`; SHA256 `f106021632fe3895fed1921be478578ccad6843999cef29c315ffa0c79828672`. Kopia jest w ignorowanym lokalnym katalogu dowodów. Ten hash jest zapisany w ProviderGrant. Konfiguracja zawiera datę przeglądu i jego termin ważności; nie jest to automatyczny audyt każdej późniejszej zmiany warunków.

## Polityka danych i limit aplikacji

Wysyłane są tylko CIK/rodzaj publicznego zasobu oraz jawnie przekazany przez użytkownika identyfikator User-Agent do SEC. Kontakt nie trafia do śledzonych plików projektu, raportów ani modeli. Payloady finansowe są wyłącznie pobierane. Brak uwierzytelnienia do filing APIs, cookies, przekierowań, proxy środowiskowych, fallbacku i zakupów.

Limit20 prób na jawnie ustalony dzień UTC jest wewnętrznym ograniczeniem aplikacji, nie deklaracją dziennej quota SEC. Każdy GET danych rezerwuje próbę w PostgreSQL przed siecią; nie ma zwrotów po błędzie. Zakończenie okna lub ważności przeglądu blokuje nowe pobrania. Zarchiwizowane wejścia istniejącego przebiegu nie są podmieniane.

## Zakres potwierdzenia jakości

Przetestowano walidację kontekstu, CIK/listingu, rocznych USD i najnowszego available10-K, zgodność accession, dokładne liczby, daty i archiwizację bajtów. Rzeczywisty odczyt Apple porównano z [Form10-K za2025](https://www.sec.gov/Archives/edgar/data/320193/000032019325000079/aapl-20250927.htm), sekcja Consolidated Statements of Operations: przychód416161 mlnUSD i wynik netto112010 mlnUSD. API przechowuje te wartości w USD; potwierdzono przeliczenie jednostki tabeli, nie pomnożono liczb ponownie w adapterze.

To dopuszczenie wąskiego lokalnego pilota. Nie certyfikuje kompletności wszystkich emitentów, zmian historycznych, praw do znaków ani danych point-in-time dla backtestu. [Kontrakt i ograniczenia implementacji](../SEC_FUNDAMENTALS.md).

## Okno pilota panelu — 2026-11-04

Na potrzeby jawnego uruchamiania analizy z panelu otwarto kolejne niepokrywające się okno 2026-11-04T00:00:00Z–2026-11-05T00:00:00Z, nadal20 prób. Nie zmieniono warunków dostawcy, daty ważności przeglądu ani starych liczników w PostgreSQL. Katalog rozszerzono o zweryfikowane symbole Alphabet GOOGL/GOOG, CIK0001652044, XNAS; importer nadal sprawdza tożsamość na podstawie rzeczywistej odpowiedzi submissions. [Zakres panelu](../PANEL.md).

Kontynuacja odbioru 2026-11-05: po przerwie poprzednie okno wygasło. Ustawiono nowe niepokrywające się okno 2026-11-05T00:00:00Z–2026-11-06T00:00:00Z z tym samym limitem20 prób, bez kasowania historii quota i bez automatycznego odnawiania.

## Katalog emitentów — 2026-11-06

Rozszerzenie tego samego publicznego źródła obejmuje wyłącznie https://www.sec.gov/files/company_tickers_exchange.json (oficjalny JSON zweryfikowany6 listopada). Katalog podaje CIK, nazwę, symbol i giełdę; nie dowodzi typu instrumentu ani kompletności danych fundamentalnych. Dopuszczone giełdy pilota to Nasdaq/XNAS i NYSE/XNYS. Odczyt zachowuje identyfikowany dostęp, TLS, brak przekierowań/proxy i istniejącą wspólną bramkę free-only, quota oraz pacing. Inne hosty/ścieżki nie są dopuszczone. Katalog jest bieżącym rejestrem, nie historycznym uniwersum PIT. Wybrany listing nadal musi być zweryfikowany w submissions przed rejestracją instrumentu.
