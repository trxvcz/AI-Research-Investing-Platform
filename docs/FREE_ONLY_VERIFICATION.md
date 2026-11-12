# Weryfikacja P4-00 — wyłącznie darmowe wywołania

To zapis odbioru etapu P4-00 przed aktywacją źródła. Aktualny stan po osobnym dopuszczeniu SEC, migracji właściwej bazy i pierwszym raporcie opisuje [SEC_VERIFICATION](SEC_VERIFICATION.md).

Odbiór lokalny: 2026-11-02. Gałąź `codex/free-only-provider-policy`. [Kontrakt, granice i dalszy krok](FREE_ONLY_PROVIDERS.md).

## Wyniki

- **605 testów Python PASS, bez pominięć**, w tym pełna regresja rejestru, raportów, snapshotów, przebiegów, workera i backup/restore. **9 testów Node PASS**. Python3.12.14 i rzeczywisty PostgreSQL17.11 na osobnym porcie55433.
- Ruff check i format: PASS (57 plików); mypy: PASS (25 modułów); pip check i drift schematów: PASS. 27 schematów v1 i 4 legacy. Brak nowych zależności. Jedno istniejące ostrzeżenie Starlette/httpx w TestClient.
- **72 testy polityki**: brak dopuszczenia bez aktualnych warunków, jakości, zerowej opłaty, zgody na rodzaj danych, zarejestrowanej implementacji i aktywnego limitu. Paid, unknown, dodatni koszt i płatny fallback nie wykonują callbacku. Secret zawsze blokowane; private wyłącznie dla local/local_only. Pusta konfiguracja nie dopuszcza dostawcy.
- Precyzja kosztu: dodatnie1e-400 i5e-324 zachowują wartość Decimal, również po serializacji/ponownej walidacji; nie stają się dowodem darmowego dostępu. Ujemny underflow, bool, ogromny nieprzedstawialny wykładnik oraz niepoprawna konfiguracja są blokowane. Bezpośredni binarny float0.0 odrzucany jako niejednoznaczny; dokładne zero z loadera nadal działa.
- **22 testy trwałego limitu**: jedna wygrywająca rezerwacja przy równoległym dostępie do ostatniego slotu, zachowanie licznika po nowym engine i błędzie, wspólna pula różnych endpointów, odmowa zmiany limitu i nakładającego się okna, aktywne daty sprawdzane zegarem DB, blokada wyzerowania/usuwania historii i bezpieczny downgrade. READ COMMITTED jest wymagane zarówno przez magazyn, jak i trigger; inne izolacje nie tworzą rekordów.
- **4 testy integracji bramki z PostgreSQL**: callback jest uruchamiany dopiero po zatwierdzonej rezerwacji; jego błąd nie zwraca limitu ani nie uruchamia płatnego zastępstwa. Nowa instancja nadal widzi wyczerpanie. Dwie bramki współdzielą ostatnią próbę. Paid i dodatnia opłata nie tworzą nawet rezerwacji.
- Selektor Node wymaga jawnego potwierdzenia darmowego dostępu, jakości, aktualnych dat i limitu. Dodatni budżet nigdy nie dopuszcza dodatniego kosztu. To nadal selektor demonstratora, bez wywoływania usług i bez własnego trwałego licznika.
- Starszy test selektora, który dopuszczał dodatni koszt przy dodatnim budżecie, zmieniono zgodnie z obowiązującym wymaganiem użytkownika. Dwie asercje aktualnego head w testach migracji workera korzystają teraz z MIGRATION_HEAD. Ochrona historycznych danych pozostaje sprawdzana pełną regresją.

## Niezależny przegląd

Pracę podzielono po ustaleniu kontraktów: selektor Node i jego testy; trwały magazyn/migracja; niezależne testy dopuszczenia; integracja koordynatora. Własność plików była rozłączna.

Read-only QA wykrył błąd odczytu ceny: JSON1e-400 parsowane jako float stawało się0.0. Zmieniono kontrakt i loader na dokładne liczby dziesiętne, dodano regresje oraz odmowę przy już zaokrąglonym zerze binarnym. Niezależny retest72/72 PASS; recenzent nie znalazł dalszych konkretnych blockerów. Sprawdzono także politykę danych, anonimizację wyjątków, kontrolę ważności po oczekiwaniu na quota, kolejność blokad i brak automatycznych zwrotów limitu.

## Stan środowiska i ograniczenia

Docker nadal jest niedostępny. Przetestowano migrację0005 na izolowanych schematach pomocniczego PostgreSQL; właściwej bazy Docker nie migrowano, nie zmieniano jej wolumenu ani DSN. Po uruchomieniu wymaga kopii bezpieczeństwa, upgrade head (0004+0005) i kontroli `/ready`. Pomocniczą bazę uruchomiono wyłącznie na czas testów.

Po zakończeniu testów pomocniczy PostgreSQL zatrzymano poprawnie. Nie pozostawiono aktywnych procesów wykonawcy ani połączeń do dostawców.

Nie zatwierdzono rzeczywistych warunków żadnego dostawcy i nie aktywowano adaptera. Hash/URL/przegląd w konfiguracji są zaufanym zapisem operatora, nie automatycznym potwierdzeniem licencji lub aktualnego cennika. Przyszły adapter musi korzystać z bramki, a także egzekwować timeouty, endpointy, limity odpowiedzi, archiwizację i PIT. Produkcja nadal wymaga auth/RBAC i oddzielnej roli bazy. Administrator może zmienić zabezpieczenia.

Nie wykonywano połączeń z dostawcami, zakupów, płatnych fallbacków ani zleceń. Koszt lokalnych zasobów nie był mierzony. Zachowano zastane pliki i dopisany plan Kronosa; nie zmieniano master planu, nie kopiowano wcześniejszych zmian z C:, nie wykonywano stagingu, commita, resetu, push ani zdalnego CI.
