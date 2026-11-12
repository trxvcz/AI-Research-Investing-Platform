# Darmowe wywołania — P4-00

Status: bramka i trwały limit są zaimplementowane. Aktualizacja SEC: po osobnym przeglądzie `config/provider-policy.json` dopuszcza wyłącznie publiczny pilot SEC; każde nieznane ID nadal jest blokowane. [Dopuszczenie](sources/SEC_EDGAR_ADMISSION.md), [rzeczywisty odbiór](SEC_VERIFICATION.md). Testy jednostkowe nadal nie wykonują połączeń z usługami.

Odbiór 2026-11-02: **605 testów Python +9 Node PASS**, bez pominięć, na PostgreSQL17.11. Ruff check/format (57 plików), mypy (25 modułów), pip check i schema drift: PASS. Eksport27 schematów v1 +4 legacy. Jedno znane ostrzeżenie Starlette/httpx dotyczy dotychczasowego TestClient. [Szczegóły weryfikacji](FREE_ONLY_VERIFICATION.md).

## Kontrakt i zaufanie

`provider_contracts.py` jest jedynym źródłem modeli ProviderGrant/ProviderPolicy. Eksporty JSON Schema znajdują się w `contracts/v1/provider-grant.schema.json` i `provider-policy.schema.json`. Konfiguracja należy do operatora serwera; nie jest przyjmowana przez HTTP, dokumenty źródłowe ani odpowiedzi modelu. Polityka i zagnieżdżone wpisy są niezmienne po walidacji. Nie dodano publicznego endpointu umożliwiającego nadanie zgody.

Każdy ProviderGrant określa ID, enabled, capability (data/model), execution (local/remote), billing, max_charge_usd, paid_fallback, hard_cap_verified, quality_pass, terms_url/terms_sha256, reviewed_at/review_expires_at, data_policy oraz quota_scope/quota_limit/quota_window_start/quota_window_end. ProviderPolicy zawiera schema_version1.0, policy=free-only-v1 i do32 unikalnych wpisów. Nieznane pola są odrzucane.

Włączenie wymaga wszystkich bramek:

- Zarejestrowana implementacja i jawnie włączony wpis z zatwierdzoną jakością.
- Billing `free_no_billing` lub `free_tier`, dokładnie zerowy limit opłaty i zakaz płatnego fallbacku. Dla free_tier dodatkowo potwierdzona blokada naliczania opłat po limicie u dostawcy. Paid, unknown i brak kosztu są blokowane bez względu na budżet.
- URL warunków HTTPS bez danych logowania i fragmentu, SHA256 rzeczywiście przejrzanych warunków oraz ważny przegląd: reviewed_at ≤ teraz < review_expires_at. Metadane nie zastępują faktycznego przeglądu operatora.
- Dozwolony rodzaj danych i aktywne okno z dostępnym limitem w PostgreSQL.

Koszt jest liczbą dziesiętną Decimal. W pliku zalecany jest zapis `"max_charge_usd": "0"`; loader zachowuje dokładność również dla liczb JSON. Dodatnie1e-400 nie staje się zerem. Bezpośredni kod Pythona powinien przekazać int0, Decimal0 lub tekst"0": binarne float0.0 jest odrzucane, ponieważ mogło powstać przez utratę precyzji. Nie wymyślamy cen ani nie uznajemy braku cennika za brak opłaty. max_charge_usd dotyczy naliczenia opłat za usługę; koszt CPU/GPU, pamięci i energii wymaga osobnego pomiaru.

`public_only` pozwala przekazać tylko dane sklasyfikowane jako publiczne. Prywatne dane są dopuszczalne wyłącznie przy execution=local i data_policy=local_only. `secret` i `no_transfer` zawsze blokują wywołanie; local_only nie może być użyte z remote. Klasyfikację nadaje zaufany kod aplikacji, nie tekst źródła. Bramka nie jest automatycznym klasyfikatorem treści ani izolacją dowolnego kodu adaptera.

## Trwały limit

Migracja `0005_provider_quota` dodaje provider_quota_windows. Kluczem jest quota_scope i początek okna. Scope musi odpowiadać rzeczywistemu współdzielonemu limitowi konta/usługi; dwa endpointy korzystające z tej samej puli używają tego samego scope. Wartość limitu i daty muszą pochodzić ze zweryfikowanych zasad, bez zgadywania chwili resetu.

QuotaStore.reserve korzysta z czasu bazy, blokady transakcyjnej scope i blokady rekordu. Działa tylko w izolacji READ COMMITTED; inne poziomy są odrzucane przed zapisem. Atomowo sprawdza aktywne okno [start,end), blokuje wyczerpanie i nakładające się okna tego samego scope, następnie zwiększa used o1. Istniejącego okna ani limitu nie można przepisać, a historii usunąć/truncate. Błąd przy końcowej kontroli terminu cofa rezerwację.

Rezerwacja zostaje zatwierdzona **przed wywołaniem adaptera**. Ponownie sprawdzamy ważność warunków po oczekiwaniu na blokadę. Jeśli później wystąpi błąd, timeout, utrata odpowiedzi lub przerwanie procesu, próba pozostaje zużyta. Brak automatycznego zwrotu, retry lub płatnego fallbacku. Nowy proces i inne instancje bramki widzą ten sam licznik. Bez dostępnej bazy nie ma wywołania dostawcy. Nowe, nienakładające się okno wymaga jawnie skonfigurowanych, zweryfikowanych dat.

Administrator bazy może zmienić zabezpieczenia. Runtime wymaga docelowo oddzielnej roli i auth/RBAC; zmiana scope przez operatora nie może służyć do obchodzenia limitu. Ta implementacja nie jest rozliczaniem rachunku u dostawcy ani kompletnym ledgerem kosztów modeli.

## Użycie przez przyszły adapter

```python
from alphasense.provider_policy import configured_gateway

# Implementacje rejestruje kod serwera, nigdy dokument ani żądanie HTTP.
# Brak zatwierdzonego wpisu blokuje również zarejestrowaną implementację.
gateway = configured_gateway({})
```

configured_gateway odczytuje ograniczony do64KiB plik polityki i podłącza QuotaStore do istniejącego ALPHASENSE_DATABASE_URL. Duplikaty kluczy, niefinitywne liczby, wadliwe dane i zbyt duży plik są blokowane bez ujawniania ścieżek lub wartości. Import SEC jest osobnym, jawnym poleceniem CLI; API i worker analizujący archiwum nie wywołują dostawcy przy starcie. Implementacja pierwszego adaptera musi korzystać z tej bramki oraz osobno obsłużyć timeouty, dozwolone endpointy, limity odpowiedzi, archiwizację exact-byte i PIT.

FreeOnlyGateway.invoke(provider_id, payload, classification=...) wykonuje jeden zatwierdzony callback. Zwraca jego wynik albo zanonimizowany ProviderDenied.code; wyjątek adaptera nie ujawnia treści dokumentu czy danych logowania. Wynik wymaga następnie walidacji kontraktu przez adapter. Cache i algorytmy deterministyczne pozostają pierwszym wyborem; ta bramka nie uruchamia modeli ani nie generuje wyników w ich zastępstwie.

Selektor Node `choose` również wymaga aktualnego potwierdzenia darmowego dostępu, quality_pass, zerowego total_cost, wyłączonego paid_fallback i dodatniego quota_remaining. Dodatni budżet nie pozwala na opłaty. To nadal wybór opcji demonstratora: nie wywołuje usług i nie zużywa trwałego limitu. Nie należy traktować go jako zamiennika bramki Python. Czasy Node są ograniczone do milisekund; wyższa precyzja jest odrzucana.

## Wdrożenie i dalsze zadanie

Docker jest dostępny: właściwa baza ma head0007 po backupie i `/ready`200. Nie zmieniano jej konfiguracji, wolumenu ani DSN. Na innym stanowisku najpierw backup i jawny `python -m alembic upgrade head`. Pełne testy używają osobnego lokalnego PostgreSQL i izolowanych danych. Cofnięcie0005 odmawia usunięcia niepustej historii limitów.

Pierwszy pilot SEC został zweryfikowany i uruchomiony. Kolejne źródła wymagają osobnego przeglądu dostępu, praw, dat i adaptera przed wpisem polityki. Plan Kronosa oraz priorytet pierwszego rzeczywistego raportu fundamentalnego pozostają bez zmian.
