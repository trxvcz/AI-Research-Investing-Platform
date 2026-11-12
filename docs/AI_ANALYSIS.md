# Gotowa analiza AI w panelu

Aktualizacja2026-11-12: nowe generowanie korzysta z maksymalnie trzech okresów w zamrożonym kontekście `report-history-v2`. Zapisano nowe GOOGL/AAPL, zachowując wcześniejsze analizy. Łącznie zarezerwowano12PLN, pozostało38PLN; to rezerwacje, nie rachunek dostawcy. [Aktualny zakres i odbiór](AI_HISTORY_ANALYSIS.md). Opis pierwszego pilota poniżej pozostaje historyczny.

Panel generuje i zapisuje polską interpretację danych istniejącego raportu: najważniejsze wnioski, mocne strony, ryzyka, pytania i ograniczenia. Wnioski prowadzą do konkretnych liczb, okresów i źródeł. To interpretacja AI wymagająca sprawdzenia, nie rekomendacja inwestycyjna ani prognoza kursu.

## Jak sprawdzić

1. Otwórz http://127.0.0.1:8082/panel/ i odśwież stronę.
2. Wybierz GOOGL albo AAPL. Domyślnie panel wybiera najnowszy zakończony raport spośród wczytanych przebiegów; ręczny wybór pozostaje zachowany.
3. Sekcja **Analiza AI** jest przed danymi finansowymi. Dla tych dwóch raportów zapisano już rzeczywiste odpowiedzi Gemini.
4. Rozwiń **Sprawdź dane**, aby zobaczyć podstawę wniosku. Otwarcie zapisanej analizy i odświeżenie wyników nie wywołują modelu.
5. **Generuj analizę AI** uruchamia pojedynczą nową próbę. Nowa wersja zachowuje wcześniejsze. Po niepewnym błędzie sprawdź zachowane zlecenie; nie twórz nowej próby w ciemno.

Formularz pozyskania danych jest pod **Nowa spółka lub odświeżenie danych**. Zadania, wykonawcy i dokumenty są w **Zaplecze i dokumenty**. Dawne sekcje techniczne pozostają pod **Obliczenia i moduły raportu**. Nie zmieniono historycznych raportów i ich sum kontrolnych.

## Zgoda i limit

Właściciel dopuścił 2026-11-11 Gemini Paid z limitem **50 PLN łącznie, bez odnawiania** i potwierdził Paid/Tier 1 obecnego klucza. To osobny wyjątek dla syntezy raportów. Darmowe źródła, brak płatnego fallbacku i research-only pozostają obowiązujące. FreeOnlyGateway i modelowa kolejka ekstrakcji dokumentów nie zostały odblokowane.

PostgreSQL rezerwuje **1 PLN przed każdą próbą**, także kwalifikacyjną. Błąd, przerwanie i restart nie zwracają rezerwy. Limit obejmuje wszystkie procesy i nie odnawia się po restarcie. Ten sam request_id zwraca zapisany stan bez kolejnego zapytania. W teście równoczesne 64 próby zaakceptowały dokładnie 50 rezerwacji. Baza blokuje reset i usunięcie historii.

To aplikacyjny limit konserwatywnych rezerwacji, nie limit faktury Google ani użycia klucza przez inne programy. W [przejrzanym cenniku](https://aistudio.google.com/docs/pricing#gemini-3.1-flash-lite) gemini-3.1-flash-lite Standard kosztuje 0.25 USD/M tokenów wejścia i 1.50 USD/M wyjścia. Żądanie ma maksymalnie 32768 bajtów, wyjście 2048 tokenów. Limit bajtów plus margines 10000 tokenów wejścia, przelicznik 10 PLN/USD i mnożnik 2 dają rezerwę poniżej 1 PLN. Brakujące usage/koszt pozostają null. Brak tools, grounding, cache dostawcy, retry i fallbacku.

Po odbiorze zarezerwowano **6 PLN**, pozostało **44 PLN**: jedna odrzucona odpowiedź kwalifikacji, trzy poprawne próbki nowego pomiaru oraz analizy GOOGL i AAPL. Nie oznacza to faktury 6 PLN.

## Zakres i jakość

Pierwszy zakres obejmuje zapisane rzeczywiste raporty z publicznych źródeł SEC. Do Gemini trafiają znormalizowane obserwacje i lista brakujących metryk, bez surowych dokumentów, sekretów i prywatnych plików użytkownika. Te same reguły działają dla obsługiwanych spółek.

Walidacja wymaga poprawnego schematu, dostępnych indeksów dowodów i braku nowych liczb/URL/HTML w narracji. Liczby pokazuje panel bezpośrednio z raportu. Poprawny cytat nie dowodzi sam w sobie prawdziwości interpretacji.

Pomiar v2 zatrzymano po odpowiedzi cytującej brakującą obserwację. Po zmianie wejścia nowy zamrożony pomiar v3 dał **3/3 poprawne odpowiedzi i niezależny przegląd semantyczny**. Obejmuje zero przychodów/brak wyniku, dodatni wynik z ograniczonym kontekstem oraz instrukcję atakującą w etykiecie źródła. Braki wskazano, atak zignorowano, nie wymyślono dynamiki ani ceny. To odbiór prywatnego pilota, nie uniwersalna kwalifikacja lub ukończony benchmark ekstrakcji dokumentów.

GOOGL zawiera tylko przychód i wynik netto; AI wskazuje brak danych do oceny trendów, zadłużenia i przepływów. Apple ma szersze dane, pozwalające zestawić przepływy operacyjne z nakładami. Przegląd Apple: **przydatna z ostrzeżeniem o zakresie**. Model użył szerszego określenia zobowiązań finansowych niż zakres dwóch części długu długoterminowego. Przy ryzykach panel pokazuje nierozwijaną uwagę o niepełnym zakresie i braku oceny płynności/wypłacalności. Uwaga zależy od metryk, nie symbolu spółki; oryginalna odpowiedź pozostała niezmienna.

GPW, wiadomości, pełna wycena, prognozy, automatyczna ekstrakcja dowolnych dokumentów i hosting Oracle pozostają do wykonania. Brak danych nie staje się zerem. Model nie ma narzędzi ani możliwości składania zleceń.

## Konfiguracja i trwałość

Jawne ustawienia serwerowe: ALPHASENSE_AI_SETTINGS_FILE i ALPHASENSE_AI_ENV_FILE. Start-Panel.ps1 rozpoznaje `.local-postgres/ai-analysis-settings.json` i wskazuje `.env`; klucz nie trafia do przeglądarki ani argumentów procesu. Prywatne dopuszczenie wiąże hash klucza, Paid, kwotę, model, daty i hashe przeglądu [warunków](https://aistudio.google.com/docs/terms)/cen oraz kwalifikację z sygnaturą kodu i schematu. Zmiana kodu, klucza lub wygaśnięcie przeglądu blokuje nowe generacje, zachowując odczyt wyników. Bieżący pilot ma przegląd ważny 24 godziny od przygotowania; jego przedłużenie wymaga odświeżenia oceny cen/warunków, bez resetowania budżetu.

Migracja 0015 dodaje kontrolę budżetu, niezmienny rejestr rezerwacji i analizy związane z revision_id/checksum. Główną bazę zaktualizowano po pg_dump; porównano wcześniejsze raporty i liczniki. API nie ujawnia audytu. Prywatnie zapisuje się prompt, hashe, czasy, surową odpowiedź i usage, jeśli zwrócono. Terminalny wynik i audyt są niezmienne.

Protokoły i wyniki pozostają w ignorowanych `.local-postgres/ai-analysis-paid-pilot-20261111*`. Projektu billingowego nie zmieniał agent; jego status potwierdził właściciel.

## Odbiór

Pełna regresja: **1512 Python PASS, 1 SKIP** (symlink niedostępny na Windows). Następnie osobny rzeczywisty pg_dump/psql restore PASS: zachowane wyniki, audyty, kwalifikacje, wykorzystany limit, idempotencja i kolejna rezerwacja bez resetu. Końcowa poprawka health/ready sprawdzona w30testachAPI: status ujawnia skonfigurowane aktywneAI, gotowość obejmuje nowetabele. Panel73/73, Node9/9 i buildPASS; Ruff/format/mypy/schematy/OpenAPIPASS. Rzeczywiste generowanie GOOGL wykonano przyciskiem w panelu; Apple również zapisano. Powtórzenie żądania Apple zwróciło ten sam wynik bez dodatkowej rezerwacji. Odbiór interfejsu potwierdził zapisane teksty, wybór nowszego raportu, schowane zaplecze i widoczną uwagę przy długu.

Końcowy test po wznowieniu sesji: uruchomiono wcześniej zatrzymany Docker i lokalne usługi. Restart panelu zachował identyczne odpowiedzi obu analiz oraz6PLN rezerwacji/44PLN pozostałego limitu. /ready200 i external_providers_enabled=true. Wykonano nowy pg_dump po zapisaniu analiz. Ten odbiór nie wykonał żadnej kolejnej generacji.
