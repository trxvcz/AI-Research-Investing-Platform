# Stan obecny — discovery P0

Data: 2026-10-30. Zakres: rzeczywiste repo `D:/repos/AI Research Investing Platform`.

To zachowany snapshot P0 sprzed wdrożenia pierwszego przyrostu. Po zatwierdzeniu ADR dodano lokalne API walidacji Python; aktualny zakres i testy: [BACKEND](../BACKEND.md), [P1 verification](../P1_VERIFICATION.md). Poniższe ustalenia o braku FastAPI opisują bazowy stan discovery.

## Potwierdzone lokalnie

- Katalog roboczy jest poprawny. Zapis, odczyt i usunięcie jednorazowego pliku kontrolnego powiodły się.
- HEAD: `6d7e726`; jedynym śledzonym plikiem jest README.md. README ma lokalne zmiany, reszta startera i master plan są nieśledzone. Nie wykonywano resetu, stagingu, commita, fetch ani push.
- Origin: `https://github.com/trxvcz/AI-Research-Investing-Platform.git`. Nie pracujemy w `trxvcz/AlphaSense`.
- Przed zmianami dokumentacyjnymi wszystkie 46 pozycji MANIFEST.sha256.json miało zgodne hashe. Manifest opisuje oryginalny starter, nie późniejsze zmiany.
- `npm test`: 4/4 PASS, Node v24.21.0. Testy używają katalogów tymczasowych i syntetycznych danych.
- Polecenie `python --version` wskazało niedostępny alias WindowsApps. Działającego interpretera Python nie potwierdzono; nie oznacza to dowodu braku innych instalacji.

## Rzeczywisty stos i zachowanie

`package.json` nie ma zależności zewnętrznych. Backend to Node.js ESM i wbudowany HTTP (`services/api/server.mjs`), frontend to statyczny JavaScript/PWA (`apps/frontend`), bez React. `services/technical/indicators.py` jest punktem rozszerzenia, nie backendem FastAPI.

`services/runtime/demo.mjs` wykonuje data → fundamental → technical → report → reviewer na syntetycznych danych. Powstają nowe katalogi raportów JSON/HTML/SVG; nie jest to pełny mechanizm niezmienności magazynu. Reviewer sprawdza skończoność SMA, nie niezależną jakość badań. API udostępnia health/ready i odczyt raportów, bez auth. Backtest celowo rzuca błąd. Brak rzeczywistych adapterów danych, wywołań LLM, brokera i zleceń.

## Kontrakty i luki

Przeczytano cztery schematy z `contracts/`. Są szkicami JSON Schema 2020-12; runtime nie uruchamia pełnego walidatora. `analysis` jest osadzone także w `report`, co grozi rozjazdem definicji. Fundamental/technical/metrics pozostają otwarte. Status miesza pochodzenie `demo` z kompletnością `partial/complete`.

`validateData` kontroluje zbiorcze available_at względem as_of oraz dodatnie ceny, ale nie obserwacyjne PIT, rewizje, okresy, jednostki, walutę i licencję. Nie gwarantuje kompletności wejść fundamentów. Schemat raportu nie przechowuje pełnego lineage obserwacji. Cztery testy nie zastępują walidacji schematów ani weryfikacji rzeczywistych źródeł.

Konfiguracje modeli/budżetów są przykładami i nie są egzekwowane przez runtime. Router wybiera według jakości i kosztu, lecz dopuszcza dodatni koszt przy dodatnim budżecie. Nie ma aktualnych płatnych wywołań, ale nie ma też systemowej blokady płatnych fallbacków.

## Audyt spoza repo

Przeczytano README, discovery, ADR-0001, roadmapę, changes.md oraz ADR-002 z pakietu audytu na C: wskazanego przez użytkownika. Według audytu kandydat obejmuje 18 zmienionych i 37 nowych plików; nie kopiowano go ani nie traktowano jego funkcji jako wdrożonych tutaj.

Historyczny błąd git status z audytu nie odtworzył się: bieżący status jest odczytywalny. Historyczne ograniczenie zapisu do C: nie dotyczy bieżącej sesji. Rekomendacja architektury pozostaje do przeglądu w ADR-0001. Płatna rezerwa z zewnętrznego ADR-002 jest wykluczona przez bieżące wymaganie użytkownika.

## Przegląd bezpieczeństwa discovery

API pozostaje lokalnym demonstratorem, nie wdrożeniem publicznym: brak auth/RBAC, limitów i trwałego audytu. Istnieją allowlista tras, CSP i escapowanie JSON w HTML; nie stanowią pełnego audytu bezpieczeństwa. Prywatne raporty nie są cache'owane przez service worker. Konieczne są testy granic ścieżek i symlinków przed obsługą niezaufanych artefaktów. Nie odczytywano sekretów, nie wysyłano dokumentów, nie aktywowano providerów. Zakres tej zmiany to dokumentacja, bez zmiany powierzchni wykonawczej.
