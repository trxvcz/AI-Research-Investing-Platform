# Developerski benchmark Gemini Free — 2026-11-11

Status: przygotowany protokół i audyt, pierwszy przebieg zatrzymany przed siecią. **Nie zmierzono jakości modelu.** Produkcyjny provider i modelowy worker pozostają wyłączone.

Właściciel potwierdził projektFree z wyłączonymbillingiem oraz przynależność obecnego klucza.env do tego projektu. Dowód lokalny wiąże potwierdzenie z hashem klucza; models.list200 potwierdziło dostępność gemini-3.1-flash-lite, ale nie dowodzi poziomu rozliczeń. Kluczy i danych połączenia nie umieszczamy w repo ani raporcie.

## Zamrożony zakres

[Kontrakt pomiaru](architecture/gemini-free-qualification-contract.md) przewiduje8 syntetycznych dokumentów publicznych, wspólny prompt document-facts-v1, brak gold w zapytaniach, maksymalnie8 prób, brak ponowień i fallbacków, rezerwacjęPostgreSQL przed siecią oraz zatrzymanie po pierwszym błędzie. Próg:7TP/0FP/0FN,0niepoprawnych odpowiedzi i2/2abstencje. Rzeczywiste materiały ORLEN/Microsoft/Apple pozostają prywatne i nie są objęte zgodą tego pomiaru.

Suite SHA256: `933e6b64ff63d09a0e7b90bbf72287b462ab6c02144cdbd09fb5b58ad3f3154a`.

Przegląd oficjalnego [cennika](https://aistudio.google.com/docs/pricing#gemini-3.1-flash-lite) wskazuje bezpłatny Standard input/output dla wybranego modelu. [Limity](https://aistudio.google.com/docs/rate-limits) zależą od projektu; nie przyjmujemy stałego RPM/RPD ani nie omijamy429. [Warunki](https://aistudio.google.com/docs/terms) ograniczają udostępnianie API Clients użytkownikom w EOG do Paid Services. Obecny zakres to własny developerski CLI; nie oznacza to ogólnego wyjątku dla CLI. Dopuszczenie docelowej aplikacji wymaga osobnego rozstrzygnięcia warunków, bez automatycznej aktywacji Free lub Paid.

## Co faktycznie się wydarzyło

- Przygotowano wszystkie8 pakietów i promptów oraz zachowano ich hashe przed próbą. Zapisano lokalne kopie warunków, cennika, billing i limitów.
- PostgreSQL zapisał1 rezerwację, bez zwrotu. Pierwszy przypadek amber-pl-million zatrzymał się lokalnie z GEMINI_RESPONSE_SCHEMA, statusemHTTP null, usage null i bez odpowiedzi.
- Przyczyną był błąd instrumentacji koordynatora: globalne zastąpienie HTTPSConnection funkcją uniemożliwiało wykonanie super() w konstruktorze bibliotekiPython. Nie był to błąd modelu ani odmowaFree.
- Osobna reprodukcja z zablokowanymi socketami potwierdziła błąd konstruktora przed próbą połączenia: **0 wywołań generateContent**,0 ukończonych przypadków. Brak pomiaruTP/FP/FN i brak twierdzenia o zerowej fakturze na podstawieHTTP.
- Przebieg zatrzymano bez ponowienia. Wyłączny plik run-claimed.json nadal blokuje ponowne uruchomienie tego audytu. Nie nadpisano wyników ani nie zmieniono gold/promptu.

Prywatne dowody znajdują się w ignorowanym `.local-postgres/gemini-free-qualification-20261111T101555Z/`: account-review, protocol, requesty, reserved/audit pierwszego przypadku, outcome i offline-diagnosis. Nie są publicznym kontraktem ani produkcyjnym audytem kolejki.

## Poprawka i weryfikacja

GeminiTransport.generate_with_receipt używa dokładnie tej samej walidacji i pojedynczego żądania co dotychczasowy adapter. Zwraca niezmienny GeminiReceipt z draft i dokładnymi, ograniczonymi do256KiB bajtami odpowiedzi. Repr ukrywa obie wartości; zapis jest jawną decyzją wywołującego. Domyślne wywołanie adaptera nadal zwraca wyłącznie szkic. BłędyHTTP nie odczytują treści odpowiedzi i nie powodująretry. To mechanizm audytu, nie dopuszczenie providera.

build_document_request wydziela dotychczasowy prompt bez zmiany treści i bez dostępu do gateway lub sekretów. Waliduje pakiet ponownie; run_agent korzysta z tego samego buildera. quality_pass pozostajeFalse w opisie ewaluacji; produkcyjna bramka jakości nie została osłabiona.

Odbiór:1470PythonPASS i1SKIP w pełnym przebiegu na PostgreSQL. Pominięto tworzenie symlinków niedostępne na tym hościeWindows. Dodatkowa regresja prawdziwego konstruktoraHTTPS z zablokowanym socketemPASS po zebraniu pełnego zestawu; komplet testów transportów63/63PASS. Panel61/61, Node9/9 i buildPASS; Ruff/format/mypy/schematy/OpenAPI/pipcheckPASS. Lokalny /ready200; trwały licznik potwierdza1rezerwację zlimitu8. Bez migracji, nowych generacji i aktywacji providera.

NiezależnyQA pierwszegoCLI nie wykrył błędu instrumentacji; nie przedstawiamy go jako dowodu rzeczywistego działania sieci. Ponowny przegląd adaptera i runnera nie zgłosił blokujących uwag; zaleconą regresję rzeczywistego konstruktora dodano i uruchomiono.

Następny etap: nowy, jawnie oznaczony przebieg developerski po poprawce, z nowym audytem i aktualnym limitem, następnie pełna ocena jakości. Ten zakończony przebieg nie zostanie wznowiony automatycznie. Nawet syntetycznyPASS nie oznacza kwalifikacji rzeczywistych raportów, aktywacji panelu lub wdrożeniaVPS.
