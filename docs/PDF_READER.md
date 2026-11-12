# Tekstowe PDF dla wspólnego agenta

Czytnik działa lokalnie i nie zawiera reguł dla konkretnych spółek. Obsługuje warstwę tekstową PDF, zapisuje lokalizatory stron i przekazuje bloki do istniejącej walidacji szkicu. Nie uruchamia Gemini, OCR ani automatycznego pobierania raportów. To kolejny fragment agenta dokumentowego, nie ukończony adapter GPW ani silnik predykcji.

## Użycie

W panelu „Szkice z dokumentów” wybierz „Dodaj dokument i szkic”, format „Tekstowy PDF (bez OCR)”, PDF oraz zapisany szkic JSON. Nadal wymagany jest istniejący szkic: sam import PDF nie generuje faktów. Daty source_available_at i as_of pozostają deklaracją użytkownika. Tekst, cytaty i wartości wymagają przeglądu przed oceną szkicu; decyzja accepted nie publikuje metryki w raporcie.

CLI, z katalogu repo w PowerShell:

```powershell
$env:PYTHONPATH='services/backend/src'
.venv/Scripts/python.exe scripts/review_document.py raport.pdf --format pdf
```

Polecenie inspect zwraca metadane i model_called=false. Opcja --draft szkic.json sprawdza zapisane cytaty i liczby offline. Nie używaj --live bez odrębnego dopuszczenia modelu, polityki danych i budżetu; bieżący przyrost nie zmienia dotychczasowych blokad.

## Zakres i ograniczenia

- Maksymalnie1MiB oryginału,100stron,512bloków,32768znaków w bloku i2MiB tekstu. Limit zdekodowanych strumieni stron8MiB; parser ma również limity obiektów, filtrów i dekompresji.
- Lokalizatory pdf:page:N:block:M, od1, bez zgadywania znaczenia kolumn. Globalne block_id mają postać block-1, block-2 itd., zgodną z istniejącym szkicem. Oryginalne bajty i SHA256 są zachowane w archiwum.
- Brak tekstu na dowolnej stronie odrzuca cały dokument. Dotyczy to także pustych stron; nie pomijamy ich po cichu. Skany bez tekstu wymagają przyszłego OCR.
- Szyfrowanie, wykryte akcje/JavaScript, formularze, osadzone pliki i nieobsługiwane filtry są odrzucane. Nie wykonujemy dokumentu ani odwołań zewnętrznych.
- Warstwa tekstowa może różnić się od obrazu strony, zawierać błędny wynik wcześniejszego OCR albo mylną kolejność kolumn. Czytnik nie potwierdza widoczności i prawdziwości tekstu. Sprawdź oryginalny dokument przed oceną faktów. Dokument i zawarte w nim polecenia pozostają niezaufanymi danymi.

Parser pypdf==7.0.1 działa w osobnym procesie: limit512MiB (Windows Job Object / Linux RLIMIT_AS), timeout8s. Windows uruchamia bezpośredni interpreter z jawną ścieżką zaufanych pakietów, aby po timeout nie pozostawić potomka launchera venv. Proces nie dziedziczy kluczy API, URL bazy ani PYTHONPATH. Brak możliwości ustawienia limitu pamięci blokuje odczyt. macOS nie jest odebrany i obecnie zostaje odrzucony. To kontrola zasobów, nie pełny sandbox systemowy.

Biblioteka jest przypięta w pyproject.toml i requirements-dev.lock. [Dokumentacja ekstrakcji pypdf](https://github.com/py-pdf/pypdf/blob/main/docs/user/extract-text.md) opisuje ograniczenia kolejności tekstu i brak OCR. Nie wprowadzamy automatycznej aktualizacji parsera. Archiwum rewaliduje pakiet przy odczycie; zmiana wersji lub zasad czytania wymaga sprawdzenia zgodności ze starymi zapisami zamiast nadpisywania historii.

## Integracja i bezpieczeństwo

Kontrakty create/summary archiwum rozszerzono o pdf; JSON Schema, OpenAPI i typy panelu są regenerowane z Pydantic. Nie ma migracji bazy ani zmian starych raportów SEC. Kolejka nadal działa w trybie validate_saved_draft, zapisując provider_called=false. Fingerprint wykonawcy obejmuje moduł czytnika PDF. Błędy biblioteki nie ujawniają treści dokumentu ani ścieżek; archiwum zachowuje ogólny kod DOCUMENT_INVALID dla nieudanego importu.

Po aktualizacji zależności i buildzie panelu trzeba ponownie uruchomić API i worker dokumentowy. Na istniejącym prywatnym wdrożeniu przebuduj obraz i odtwórz kontenery aplikacji z tą samą nazwą projektu i wolumenami. Nie usuwaj wolumenów i nie wykonuj nowej inicjalizacji sekretów.

## Weryfikacja

Testy używają wyłącznie syntetycznych PDF: kilku emitentów i stron, cytatów/liczb, archiwum PostgreSQL, oryginalnych bajtów oraz wykonania offline bez publikacji. Obejmują też szyfrowanie, brak tekstu, aktywną zawartość, cykle, bomby dekompresyjne i limity.

Rzeczywisty proces Windows ma sprawdzony limit pamięci, a regresja timeout porównuje PID uruchomionego procesu z PID właściwego interpretera. Niezależny QA potwierdził zakończenie procesu przez Windows OpenProcess/WaitForSingleObject. Próba na Linuxie przeszła jako użytkownik10001, bez sieci, na read-only filesystem z własnym limitem pamięci i kontrolą RLIMIT parsera. VPS Oracle i rzeczywisty benchmark dokumentów wielu spółek pozostają nieodebrane.

Końcowy odbiór2026-11-10:1284 Python PASS w jednym pełnym przebiegu(194,21s), panel53/53, Node9/9 i TypeScript/Vitebuild PASS. Ruff/format/mypy, zgodność schematów/OpenAPI i pipcheck PASS. Znane ostrzeżenie deprecacyjne Starlette/httpx pozostaje. Niezależny QA bez pozostałych blokujących uwag po poprawkach konfiguracji pypdf, wyboru pliku i timeoutu Windows. Po restarcie lokalnego API oraz bezczynnego workera dokumentów /ready i wcześniejszy raportGOOGL zwracają200; trzy rodzaje wykonawców mają aktualny heartbeat. CLIinspect syntetycznego PDF zwrócił2bloki i model_called=false. Nie wykonywano odbioru wizualnego formularza ani importu rzeczywistego raportu emitenta; przepływHTTP archiwum sprawdzono w izolowanych schematach PostgreSQL. Bez migracji i nowych wywołań modeli.
