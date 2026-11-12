# Kronos — opcjonalne scenariusze cenowe i hosting

Data: 2026-11-02. Status: plan funkcji, bez wdrożenia modelu, endpointów ani hostingu. Aktualizacja na prośbę właściciela po omówieniu Kronosa. Nie upoważnia do zakupu infrastruktury, płatnych API ani wysyłania danych na zewnątrz.

## Zakres produktu

Opcjonalna funkcja „Scenariusze cenowe” na stronie instrumentu: historia oddzielona od przyszłych scenariuszy, horyzont 5 lub 20 sesji, data odcięcia, pochodzenie danych, wersja modelu oraz porównanie z prognozą „ostatnia cena”. Pilot: jeden rynek, mała jawna lista instrumentów equity/ETF, świece dzienne i jeden zakwalifikowany model mini albo small. Bez fine-tuningu, automatycznych zleceń, nowych klas aktywów i generowania przy każdym otwarciu strony.

Feature pozostaje eksperymentalny, domyślnie wyłączony. Nie jest rekomendacją inwestycyjną. Pasma oznaczają rozrzut wygenerowanych scenariuszy; dopiero niezależna kalibracja pozwala przypisywać im deklarowane pokrycie. Nie wyświetlać niezweryfikowanego „prawdopodobieństwa wzrostu”. Niedostępny model nie blokuje raportu fundamentalnego; część scenariuszowa ma jawny status i przyczynę.

## Architektura docelowa

```text
zweryfikowane darmowe źródło EOD
    → walidacja świec / sesji / dostępności → immutable snapshot + hash
    → zamrożone wejście ForecastRequest
PWA → FastAPI → kolejka PostgreSQL → osobny worker Kronosa
              ↑                         ↓
              └── wynik/cache ← walidator prognozy + artefakt
```

Zachować modularny backend z ADR-0001. Model pracuje poza procesem HTTP, w osobnym środowisku/obrazie z przypiętymi zależnościami PyTorch i wagami. API nie ładuje modelu. Wykorzystać wzorzec kolejki PostgreSQL, idempotencji i leases/fencing z [workera deterministycznego](../AUTOMATIC_WORKER.md); nie dodawać Redis/Celery bez wykazanej potrzeby. Obecny worker obsługuje wyłącznie swój deterministyczny pipeline i nie uruchamia Kronosa.

Nowy identyfikator pipeline, np. `kronos-scenarios-v1`, wymaga osobnej implementacji, kontraktów i testów. Długie inferencje muszą odnawiać lease także podczas obliczeń, a zapis wyniku sprawdzać aktualny fencing token. Restart może ponowić obliczenie, ale nie publikować duplikatu. Limit prób, czas wykonania, długość kolejki i współbieżność muszą być ograniczone; start od jednej inferencji naraz. Kill switch zatrzymuje nowe zadania modelu; anulowanie bieżącej pracy i sposób rozliczenia wymagają jawnej semantyki.

## Projekt kontraktów — jeszcze niewdrożony

Przed kodem przygotować jedną definicję Pydantic i generowane JSON Schema/OpenAPI. Poniższe nazwy opisują projekt, nie dostępne API:

- `PriceBarDataset`: instrument, waluta, interwał, kalendarz/strefa sesji, konwencja korekt split/dividend, uporządkowane świece, źródło/licencja, snapshot/hash oraz dostępność każdej użytej obserwacji. OHLC skończone i dodatnie, high/low spójne z open/close; brak duplikatów i niewyjaśnionych luk sesyjnych. Nie utożsamiać braku wolumenu z zerowym obrotem.
- `ForecastRequest`: instrument_id, as_of, zamrożone snapshot_ids/hash, wersja preprocessingu i kalendarza, wybrana wersjonowana konfiguracja modelu, lookback, horyzont, liczba ścieżek i seed. Klient wybiera wyłącznie konfiguracje z allowlisty; bez dowolnych ścieżek, URL modeli lub kodu. Przyszłe daty wynikają z kalendarza sesji. Wszystkie wejściowe available_at ≤ as_of; nieznane availability blokuje historyczny eksperyment.
- `ForecastArtifact`: forecast_id/run_id, status i przyczyna, generated_at, input_as_of, target timestamps, snapshot hashes, identyfikator/revision/hash modelu i tokenizera, SHA kodu, preprocessing, parametry sampling/seeds, urządzenie i wersje runtime, czas oraz zmierzone zasoby. Prognozy przechowywać osobno od historycznych obserwacji; przyszłe target timestamps nie są observation.available_at. Zachować ścieżki i zdefiniowane kwantyle oraz baseline, identyfikator ewaluacji i ograniczenia. Odrzucać NaN/Infinity i ekonomicznie niespójne OHLC, bez cichej naprawy.
- Cache obejmuje pełną tożsamość wejścia, wag/tokenizera, preprocessingu, kalendarza, parametrów i wersji obliczeń. Zakres uprawnień/danych ogranicza współdzielenie cache. Nowy snapshot lub model daje nowy wynik; nie nadpisuje historii. Seed wspiera audyt, nie gwarantuje zgodności bitowej między różnymi urządzeniami.
- Projekt API: asynchroniczne utworzenie zadania (HTTP 202), odczyt statusu i pobranie wyniku, z auth, idempotency key, limitami i kontrolą dostępu do instrumentu/artefaktu. Dokładne ścieżki ustalić w zadaniu kontraktów. Nie udawać, że istnieją w obecnym OpenAPI.

Obecny `ReportContent` wymaga null model_provenance i pustego chart_artifact_ids. Nie wciskać prognozy w obserwacje available ani nie obchodzić tych ograniczeń. Najpierw osobny artefakt; integracja raportowa wymaga jawnej nowej wersji/rozszerzenia kontraktu i czytnika, bez przepisywania starych raportów. Limit 1000 obserwacji ResearchInput nie jest formatem transportowym szeregu świecowego — ustalić własne limity rozmiaru i pojemność archiwum (dziś snapshot maks. 1 MiB).

## Bramka danych i jakości

1. Potwierdzić konkretne darmowe źródło, licencję użycia/wyświetlania, limity i politykę danych. Brak prawa redystrybucji blokuje publikowanie świec/prognoz do czasu wyjaśnienia warunków. Nie wybierać dostawcy na podstawie tego dokumentu.
2. Przejrzeć i przypiąć kod, wagi/tokenizer, ich licencje i zależności; bez uruchamiania pobranego repo/web UI. Upstream domyślnie uzupełnia brakujący volume/amount zerami, a amount bywa wyliczany przybliżeniem. W pilocie wymagać kompletnych wejść, blokować te ścieżki; ewentualny przyszły wariant OHLC-only wymaga odrębnej jawnej metodologii.
3. Tani test deterministyczny fixture: PIT, missing ≠ 0, sesje, korekty, hash/cache i walidacja wyjścia. Następnie lokalny benchmark mini/small dla tego samego lookback/horyzontu/liczby ścieżek. Mierzyć cold/warm start, p50/p95 latencji, RAM/VRAM, przepustowość, rozmiar artefaktów i koszt zasobów; nie deklarować zera bez pomiaru.
4. Przed eksperymentem zamrozić uniwersum, okresy, baseline ostatniej ceny, metryki (MAE/MASE close, pokrycie i szerokość pasm), agregację oraz liczbowy próg poprawy i limit latencji/zasobów. Obsłużyć niezdefiniowany mianownik MASE bez podstawiania zera. Walk-forward i nienaruszany zbiór OOS; konfiguracje wybierać na walidacji, nie na końcowym teście. Dla nakładających się horyzontów uwzględnić zależność błędów przy ocenie niepewności.
5. Zweryfikować zakres i koniec pretrainingu wag. Chronologiczny split wejścia nie usuwa możliwego przecieku przez wagi. Gdy zakres treningu nieznany, oznaczyć ograniczenie, prowadzić obserwację prospektywną na zamrożonej wersji; nie deklarować czystego OOS na nieudowodnionym okresie.
6. Włączyć feature dopiero po przejściu zapisanych bramek jakości/kosztu i bezpieczeństwa. Porażka → pozostawić baseline/wyłączony eksperyment; większy model tylko po błędzie bramki, w uprzednio dopuszczonym budżecie, bez płatnego fallbacku. Nie przekształcać wyniku w strategię wykonywaną przez LLM.

Upstream uśrednia próbki w `sample_count`; adapter musi zachować pojedyncze ścieżki, np. niezależnymi wywołaniami z jedną próbką, i przetestować agregację. Nie wyliczać pasm z już uśrednionego wyniku.

## Hosting i eksploatacja

Pierwszy etap: lokalny pilot, bez zakupu hostingu. Mini/small porównać na dostępnym CPU; użycie lokalnego GPU tylko po pomiarze potrzeby i dostępności. Nie podawać niezweryfikowanych minimów RAM/VRAM ani cen. Wagi pobierać w kontrolowanym etapie przygotowania, weryfikować i przechowywać lokalnie; inference bez konieczności pobierania plików z Internetu.

| Wariant planowany | Warunek wyboru | Konsekwencje |
|---|---|---|
| Lokalnie: API, PostgreSQL, worker | Pilot i użytek własny | Brak zakupów; praca tylko przy włączonym komputerze, koszt zasobów nadal mierzony |
| Aplikacja na serwerze, worker lokalny | Potrzebny dostęp zdalny, akceptowana kolejka offline | Prywatny tunel lub dedykowany uwierzytelniony protokół pobierania zadań; brak publicznego DB i brak obecnego zdalnego claim API. Wymaga osobnej implementacji |
| Jeden serwer CPU, oddzielne procesy/kontenery | Benchmark spełnia ustalone SLO i budżet | API/DB mają rezerwę zasobów; limity workera, auth/TLS, backupy i odtwarzanie |
| Oddzielny worker GPU | Udowodniona potrzeba przepustowości po błędzie bramki CPU | Rozruch, bezczynność, dysk i transfer w pełnym koszcie; limit budżetu i zatrzymanie po pracy. Brak automatycznego wynajmu |

Host aplikacji nie musi mieć GPU. Przeglądanie zapisanych raportów działa przy wyłączonym workerze, a UI pokazuje queued/unavailable zamiast obiecywać natychmiastową prognozę. Harmonogram po zamknięciu sesji jest późniejszym zadaniem; MVP uruchamiane na żądanie i korzysta z cache.

Przed wystawieniem usługi: TLS/reverse proxy, auth i izolacja dostępu do zadań, rate limits, brak publicznych portów DB/modelu, odseparowane role DB, sekrety tylko w API/adapterze, egress allowlist, skan zależności/obrazów i przypięte wersje. Worker dostaje wyłącznie dopuszczone dane świecowe; bez dokumentów użytkownika i sekretów. Hosting zewnętrzny także wymaga polityki danych.

Metryki: wiek kolejki, failed/retry, latencja cold/warm, świeżość danych, cache hit, RAM/VRAM, zasoby/koszt zadania oraz jakość prognoz po nadejściu realizacji. Backup obejmuje bazę, artefakty, konfiguracje i identyfikatory wag; test restore ma odtworzyć powiązania/hash. Definicje RPO/RTO/SLO i runbook awarii poprzedzają produkcję. Brak deklaracji 24/7/HA na podstawie Compose.

## Źródła i zależności

Dokumentacja upstream sprawdzona 2026-11-02: [repozytorium i warianty modeli](https://github.com/shiyu-coder/Kronos), [predyktor: CPU/CUDA/MPS, imputacja, uśrednianie próbek](https://github.com/shiyu-coder/Kronos/blob/master/model/kronos.py), [zależności](https://github.com/shiyu-coder/Kronos/blob/master/requirements.txt). Linki master są ruchome; zadanie implementacyjne musi zapisać konkretny commit i rewizje wag. Nie przeprowadzono lokalnego benchmarku ani oceny wyników.

Zadania i kolejność: [KR-00–KR-06](../roadmap/issues.md#kronos--opcjonalne-scenariusze-cenowe-2026-11-02). [ADR-0001](../adr/0001-platform-architecture.md) pozostaje w mocy; moduł nie zmienia Python/React ani granic research-only.
