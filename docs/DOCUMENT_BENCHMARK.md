# Lokalna ocena zapisanych szkiców

Etap P4-01b2a dodaje evaluator wspólnego agenta dokumentowego. Porównuje zamrożone dokumenty, ręcznie opisane oczekiwane fakty i zapisane odpowiedzi. Nie uruchamia modelu, nie wymaga PostgreSQL ani VPS i nie wczytuje.env. Nie dodaje nowego widoku panelu ani automatycznej ekstrakcji faktów.

## Uruchomienie

Z katalogu repo, PowerShell:

```powershell
$env:PYTHONPATH='services/backend/src'
.venv/Scripts/python.exe scripts/benchmark_documents.py --suite services/backend/tests/fixtures/document-benchmark.synthetic.json --responses services/backend/tests/fixtures/document-benchmark-reference.synthetic.json
```

Otrzymasz podsumowanie z licznikami i hashami, bez dokumentów, cytatów i identyfikatorów przypadków. Opcja --output NOWY_PLIK.json zapisuje pełny raport przypadków, odmawiając nadpisania istniejącego pliku. Raport zawiera identyfikatory i oceny, ale nie surowe dokumenty ani odpowiedzi. Na POSIX plik powstaje z uprawnieniami0600; na Windows obowiązują ACL katalogu. Przechowuj własne zestawy i wyniki w prywatnym, ignorowanym katalogu.local-postgres albo poza repo.

Kod wyjścia0 oznacza ukończony pomiar, także gdy wynik jest słaby. Kod2 oznacza nieprawidłowe wejście lub błąd zapisu; komunikat nie zawiera treści źródła i ścieżek. To nie jest polecenie aktywacji providera lub kwalifikacji modelu.

## Co mierzymy

Każdy kandydat przechodzi istniejącą walidację schematu, cytatu, tokenu liczbowego i przeliczenia skali. Następnie porównujemy dokładnie metrykę, wartość Decimal, walutę, początek/koniec okresu i zakres consolidated/separate z ręcznym gold:

- TP: poprawnie wsparty kandydat dopasowany do jednego oczekiwanego faktu.
- FP: nieoczekiwany fakt, błędna semantyka, odrzucony cytat/liczba lub duplikat.
- FN: oczekiwany fakt bez dopasowanego kandydata.
- evidence_rejections: odrzucone fakty, które nie przeszły istniejącej kontroli cytatu/liczby/skali; stanowią częśćFP.
- invalid_responses: niepoprawny JSON lub schemat odpowiedzi. Nie liczymy go jako poprawnej abstencji. Ocena całego szkicu jest odrzucona; oczekiwane fakty stają sięFN.
- successful_abstentions: poprawne facts=[] wyłącznie w przypadku z pustym gold.

Precision toTP/(TP+FP), recall toTP/(TP+FN). Raport zachowuje liczniki ułamka, a wartość do wyświetlenia zaokrągla do6miejsc ROUND_HALF_EVEN, bezfloat. Brak mianownika daje null, nigdy sztuczne0lub1. Wysokie precision/recall nie znoszą invalid_responses ani błędów abstencji; raport nie ma automatycznego progu kwalifikacji.

Niepoprawny szkic przy pustym gold daje invalid_response=true i successful_abstention=false, nawet jeśli nie ma faktów do policzenia jakoFP/FN. Nie interpretuj samych dwóch wskaźników jako pełnego wyniku.

## Zamrożenie zestawu

Pydantic jest źródłem trzech schematów w contracts/v1/document-benchmark-*.schema.json. Suite zawiera dokumenty jako canonicalbase64 z SHA256, klasyfikację, jawne data_origin, issuer_label, gold i daty source_available_at/as_of. Zestaw ma1–32przypadki, pojedynczy oryginał do1MiB, suma do8MiB. Daty i gold pozostają deklaracją autora zestawu, a nie automatycznym potwierdzeniem praw źródła lub dostępności historycznej.

ResponseSet musi wskazywać suite_sha256 i dokładnie te same case_id oraz document_sha256. Brak, nadmiar, duplikat lub zmiana dokumentu/gold blokuje cały pomiar. Nie pomijamy niewygodnych przypadków. Hash suite obejmuje także gold i metadane, obliczone z kanonicznego zserializowanego kontraktu (sort_keys, zwięzłe separatory, UTF8). API pomocnicze canonical_hash jest w alphasense.document_benchmark. Report zachowuje hash całego zestawu odpowiedzi i scorer_version.

CLI czyta najwyżej16MiB każdego wejściowego plikuJSON i odrzuca duplicatekeys/NaN. Surowy szkic ma dodatkowy limit256KiBUTF8. Nie ma URL do pobrania, narzędzi, dostępu do konta dostawcy ani ukrytego fallbacku. Dalsza powtarzalność wymaga zachowania wersji kodu, locka zależności i wejściowych plików; same hashe nie przechowują dokumentów. Zmiana czytnika PDF lub reguł walidacji wymaga ponownego pomiaru na zachowanym zestawie.

## Próbki a jakość modelu

Dołączone8przypadków dotyczy3fikcyjnych emitentów: tekstPL/EN, HTML iPDF, tys./mln., liczby ujemne, dwa okresy i zakres jednostkowy. Dwa przypadki wymagają abstencji, w tym dokument z niezaufaną instrukcją. Wszystkie są jawnie synthetic, a odpowiedzi hand_authored_reference zostały napisane ręcznie. Oczekiwane7TP i2abstencje służą testowi evaluatora, nie są wynikiem benchmarku Gemini.

Każdy raport ma qualification_status=not_qualified_offline. saved_unverified_response również nie dowodzi modelu, jego wersji, kosztu lub faktycznego wywołania. Gold trzeba sprawdzić niezależnie; wynik mierzy zgodność z nim. Przed aktywacją potrzebne są dopuszczone rzeczywiste dokumenty różnych emitentów i układów, niezależny gold oraz zamrożone wcześniej progi jakości, potwierdzona polityka danych, darmowy projekt/model lub osobno zatwierdzony budżet. Jednorazowy wcześniejszy pilot Paid nie upoważnia do kolejnych wywołań.

OCR, operacyjna ekstrakcja modelowa, telemetria prawdziwych wywołań i publikacja zweryfikowanych faktów pozostają osobnymi zadaniami. Wdrożenie Oracle jest odłożone; ten etap go nie uruchamia.

## Odbiór2026-11-10

Pełna regresja1334PythonPASS w jednym końcowym przebiegu(188,98s), w tym50testów benchmarku iCLI. Node9/9 i panel53/53PASS; Ruff/format/mypy, schematy/OpenAPI i pipcheckPASS. Pozostaje znane ostrzeżenie deprecacyjne Starlette/httpx. NiezależnyQA bez blokujących uwag, z osobną próbą nooverwrite i redakcji błędów duplicatekeys/NaN/nieprawidłowegoUnicode. RzeczywistyCLI zapisał nowy wynik do ignorowanego.local-postgres; /ready lokalnego panelu nadal200. Nie zmieniono runtimeAPI, panelu ani bazy w tym etapie; bez migracji i wywołań modeli.

Referencyjny zestaw ręczny dał7TP/0FP/0FN i2poprawne abstencje. Kontrolowana zmiana waluty w poprawnie cytowanym fakcie oraz uszkodzenie drugiej odpowiedzi dały6TP/1FP/1FN,1invalid_response i1poprawną abstencję. To obserwacje testu narzędzia, nie wyniki modelu.
