# Wspólny agent analizy dokumentów

Decyzja użytkownika: nie tworzyć parsera dla każdej spółki. Dla prywatnej platformy budujemy wspólne czytniki formatów oraz agenta semantycznego, a nie listę reguł ORLEN/Apple/kolejnych emitentów. Wybrany kandydat dostawcy to Gemini API w zweryfikowanym bezpłatnym projekcie. Samo posiadanie klucza nie dowodzi bezpłatności modelu ani twardego limitu opłat.

## Podział odpowiedzialności

Adapter źródła odpowiada za legalny dostęp, tożsamość instrumentu, daty i oryginalne bajty. Czytnik formatu tworzy neutralne bloki z lokalizatorami. Agent proponuje metryki, wartości, skale, okresy i cytaty. Deterministyczna kontrola sprawdza schemat, istnienie cytatu w bloku, pełny token liczbowy i przeliczenie skali. Znaczenie kolumn, waluta, konsolidacja i okres pozostają przedmiotem oceny jakości i przeglądu semantycznego. Cytat nie dowodzi sam z siebie poprawnej interpretacji.

Wynik to szkic `needs_review`, `rejected` albo `blocked`. Nie jest automatycznie obserwacją available ani nowym raportem. Model nie ma narzędzi, dostępu do brokera, kodu wykonawczego lub dowolnych URL. Dokument jest niezaufanymi danymi, nie instrukcją dla programu. Nie obiecujemy skuteczności każdego formatu ani każdego sprawozdania.

## Bieżący zakres

Wspólne czytniki: tekst UTF-8, statyczny HTML, XLSX oraz tekstowy PDF w osobnym procesie z limitami. [Zakres PDF i ograniczenia](PDF_READER.md); OCR pozostaje nieobsługiwany. XLSX wymaga kontroli ZIP/XML, limitów dekompresji, ścieżek i relacji; makra, odwołania zewnętrzne i formuły są odrzucane. Formuł nie wykonujemy ani nie uznajemy starych cachedvalues za dowód. HTML nie jest pełnym rendererem CSS, a odczytane bloki są wyłącznie tekstem.

Kontrakty: document-packet.schema.json, document-extraction-draft.schema.json oraz document-agent-result.schema.json. Nowe moduły nie zmieniają starszych raportów SEC. Obecna kolejka analityczna nadal obsługuje pipeline SEC; wpięcie zadań dokumentowych i bezpieczna publikacja wymagają osobnego kontraktu i bramek jakości.

## Użycie lokalne

Z ustawionym `PYTHONPATH=services/backend/src` można uruchomić `python scripts/review_document.py PLIK --format text` (lub html/xlsx). Domyślna klasyfikacja to private. Bez flagi live nie wywołuje modelu i wypisuje tylko metadane pakietu. `--draft PLIK_JSON` sprawdza zapisany szkic offline. `--output NOWY_PLIK` zapisuje wynik UTF-8 bez nadpisywania istniejącego pliku. Opcjonalne `--env-file .env` jawnie ładuje tylko GEMINI_API_KEY, GOOGLE_API_KEY i ALPHASENSE_GEMINI_MODEL; istniejące zmienne procesu mają pierwszeństwo. Plik nie jest wykonywany ani interpolowany, a błędy nie zawierają wartości. Samo załadowanie konfiguracji nie włącza dostawcy ani sieci.

`--live` korzysta z GeminiTransport za istniejącym FreeOnlyGateway i trwałą quotaPostgreSQL. Brak dopuszczonego provideragrantu blokuje wywołanie. Wyjątki dostawcy nie ujawniają dokumentu ani klucza. Brak retry, płatnego fallbacku, narzędzi i groundingsearch.

## Konfiguracja Gemini

Do oceny zapisanych odpowiedzi służy [lokalny benchmark](DOCUMENT_BENCHMARK.md). Pracuje offline i nie odblokowuje modelu. Zestaw syntetyczny testuje poprawność evaluatora; kwalifikacja na rzeczywistych dokumentach różnych emitentów pozostaje do wykonania.

Klucz pozostaje w `GEMINI_API_KEY` lub `GOOGLE_API_KEY` w środowisku procesu, model w `ALPHASENSE_GEMINI_MODEL`. Nie wklejać klucza do czatu ani do Git. Dostawca nie jest włączony w polityce tego przyrostu. Przed pierwszym wywołaniem trzeba sprawdzić bieżący model, projektFree/billing, twardą blokadę opłat, warunki danych, zmierzyć jakość i zatwierdzić grant z limitem. Prywatnych lub tajnych plików nie dopuszczamy do zewnętrznego modelu; początkowy kandydat to public_only.

[Ocena dostawców i oficjalne źródła](sources/FREE_DOCUMENT_MODELS.md). Nie wyciągać wniosku, że darmowy model gwarantuje brak przechowywania treści lub że prywatny charakter platformy sam upoważnia do przesyłania dokumentów dostawcy. Warunki konkretnego źródła i polityka modelu muszą pasować do przesyłanego materiału.

## Odbiór implementacji

Końcowa regresja 2026-11-10: 987 testów Python PASS na PostgreSQL Docker (144,87 s), w tym 57 agenta, 20 czytników, 58 transportów i 13 konfiguracji. Ruff, format (90 plików), mypy (47 modułów), schematy, OpenAPI oraz Node 9/9 PASS. Jedno ostrzeżenie deprecacyjne Starlette/httpx, bez błędów. CLI z `--env-file .env` potwierdzono w trybie inspect: model_called=false.

CLI inspect syntetycznego dokumentu zwrócił metadane bez modelu. Offline szkic „12,5 mlnPLN” został przeliczony dokładnie do12500000 i oznaczonyneeds_review. Przełączenie live bez dopuszczonego providera zwróciłoPROVIDER_NOT_APPROVED; nie wykonano sieci i nie wysłano dokumentu.

NiezależnyQA wykrył możliwość wycięcia mantysy/wykładnika z1e6; poprawiono w oryginalnym kontekście i dodano regresje. Nie deklarujemy jakości rzeczywistego Gemini, obsługi każdego dokumentu ani predykcji. Stan przed pilotem opisanym poniżej: brakowało konfiguracji klucza/projektu i kwalifikacji modelu. Sama subskrypcja Pro nie rozstrzyga planu API. [RozliczeniaGeminiAPI](https://ai.google.dev/gemini-api/docs/billing).

Przed publikacją w raportach potrzebne są także utrwalone model_id, wersja promptu, request/responsehash i metadane użycia. Obecny wynik jest szkicem do przeglądu, nie końcową rewizją analizy.

## Kontrola klucza i planu2026-11-09

Klucz zapisany lokalnie w ignorowanym `.env` został zweryfikowany wyłącznie odczytem listy modeli (`models.list`, HTTP200). Nie wypisywano klucza i nie przekazano dokumentów. Lista nazw modeli jest lokalnym dowodem dostępności, nie bezpłatności. Wpis ALPHASENSE_GEMINI_MODEL nie był prawidłowym identyfikatorem; nie nadpisano pliku użytkownika.

Użytkownik potwierdził Paid/Tier1 lub wyższy dla projektu powiązanego z kluczem. Na tym etapie zasada free-only blokowała generowanie; nie aktywowano grantu ani nie wykonano inferencji. Późniejszy wyjątek jednorazowy opisano poniżej. Kolejny krok wymaga osobnego projektu Free z wyłączonym billingiem (jeśli dostępny dla konta/regionu), jego klucza oraz ponownej kwalifikacji aktualnego modelu. Nie zmieniano rozliczeń obecnego projektu.

OdczytAPI pokazał m.in. gemini-2.5-flash i gemini-2.5-flash-lite jako dostępne. To obserwacja konkretnego konta, korygująca wcześniejszą ogólną uwagę o wycofaniu modelu; nie jest zgodą na aktywację ani dowodem darmowego planu.

## Jednorazowy pilot Gemini Paid — 2026-11-10

Użytkownik wyraźnie dopuścił test z limitem1PLN, a po pierwszym błędzie osobno jedną dodatkową próbę diagnostyczną w tym samym łącznym limicie. To wyjątek jednorazowy, nie zgoda na stały płatny ruch ani zmiana produkcyjnej zasady free-only. Nie włączono providera w provider-policy.json.

Pierwsza próba gemini-2.5-flash-lite zwróciła lokalnyPROVIDER_FAILED bez szczegółu przyczyny; konserwatywnie zarezerwowano0.82527379456PLN. Dalsze countTokens dla tej nazwy zwróciło404 i nie wykonano dodatkowej generacji na tym modelu. Dodatkowa próba została najpierw odrzucona przez automatyczny przegląd jako poza zgodą na pojedynczy test; kontynuowano dopiero po wyraźnej ponownej zgodzie użytkownika.

Dla aktualnego gemini-3.1-flash-lite sprawdzono oficjalny cennik Standard:0.25USD/mln tokenów wejścia i1.50USD/mln wyjścia. countTokens200 poprzedził pojedynczą dodatkową generację, maxOutputTokens4096, bez narzędzi/grounding/cache/retry. Dla kontroli budżetu użyto zliczonych tokenów+10000 marginesu wejścia oraz dwukrotnego mnożnika kursu NBPUSD3.9199 z2026-11-09. Łączna konserwatywna rezerwa obu prób0.89484417976PLN <1PLN. To nie jest potwierdzenie kwoty faktury.

Rzeczywista odpowiedź:HTTP200, finishReasonSTOP, promptTokenCount920, candidatesTokenCount211. Szacunek udanego wywołania wg tych tokenów:0.0005465USD, około0.00214222535PLN przed podatkami/różnicami kursowymi. Użyto wyłącznie krótkiego dokumentu syntetycznego, bez dokumentów użytkownika. Agent wydobył revenue12500000PLN z12,5mln, zakresconsolidated, okres2025. Wynikneeds_review, ponieważ znaczenie metryki/okresu wymaga oceny semantycznej. Jedna próbka nie dowodzi jakości na dowolnych spółkach.

Odpowiedź miała dodatkowe polethoughtSignature; adapter teraz akceptuje ten ograniczony string jako metadane i pomija go, nadal odrzucając narzędzia/inne pola. Zapisana rzeczywista odpowiedź przeszła odtworzenie offline przez adapter i walidator, bez nowego wywołaniaAPI. W.env poprawiono tylko identyfikator modelu na gemini-3.1-flash-lite; klucz nie został wyświetlony. Rezerwacje i odpowiedź są w ignorowanym.local-postgres; nie publikujemy ich w Git.

Źródła cen i kursu:https://ai.google.dev/gemini-api/docs/pricing.md oraz https://api.nbp.pl/api/exchangerates/rates/a/usd/?format=json. Kolejne płatne wywołanie wymaga osobnego zatwierdzonego budżetu.
