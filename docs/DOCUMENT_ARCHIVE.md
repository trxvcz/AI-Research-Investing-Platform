# Archiwum szkiców i przegląd faktów

Ten przyrost dodaje lokalny import oryginalnego dokumentu i zapisanego szkicu JSON oraz historię oceny faktów. Działa wspólnie dla emitentów: tekst UTF-8, statyczny HTML i XLSX korzystają z tych samych czytników. Nie dodaje parserów spółek, wywołań modelu, pobierania adresów URL ani automatycznej publikacji danych w raportach.

## Kontrakt i zakres

`DocumentArchiveCreate` zawiera identyfikator UUID, tytuł, opcjonalny istniejący instrument, format, klasyfikację, oryginalne bajty w base64, zapisany `ExtractionDraft` w `draft_json`, daty `source_available_at` i `as_of` oraz opcjonalne deklaracje modelu i wersji promptu. Daty muszą mieć strefę; dostępność źródła nie może przekraczać `as_of`. Import nie weryfikuje faktycznej daty publikacji ani powiązania ekonomicznego dokumentu ze spółką. To metadane podane przez importującego.

Pochodzenie ma stałą wartość `unverified_offline_import`. Nazwa providera/modelu nie jest potwierdzeniem wykonania wywołania. Import nie przyjmuje klucza API, nie korzysta z Gemini i nie sprawdza billing. Klasyfikacja private jest domyślna; także secret pozostaje wyłącznie lokalnym zapisem. Ten etap nie rozszerza polityki wysyłania danych do dostawców.

Oryginał jest ograniczony do 1 MiB, szkic do 256 KiB UTF-8. Czytnik dodatkowo ogranicza rozpakowanie XLSX. PDF/OCR pozostaje nieobsługiwany. Serwer ogranicza cały strumień JSON przed parsowaniem do 4 MiB, a komendę przeglądu do 16 KiB. Tekst lub HTML w panelu jest wyświetlany jako tekst; oryginał pobiera się jako attachment/octet-stream z nosniff.

Serwer sam tworzy pakiet bloków i ponownie sprawdza szkic: dokładne cytaty, tokeny liczbowe i przeliczenie skali. Nie przyjmuje gotowego wyniku walidacji od klienta. Błędny szkic można zachować jako rejected/blocked do diagnostyki; nie daje to faktów do publikacji.

## Trwałość i decyzje

Migracja `0010_document_archive` dodaje `document_archives` i `document_reviews`. Oryginalne bajty, szkic, pakiet, wynik oraz hashe są niezmienne. Triggery odrzucają UPDATE, DELETE i TRUNCATE obu tabel. Downgrade odmawia usunięcia niepustego archiwum. Właściciel bazy może zmieniać zabezpieczenia: nie jest to ochrona przed administratorem PostgreSQL.

UUID importu identyfikuje zamrożony zestaw danych. Powtórzenie identycznego żądania zwraca zapis; zmiana zawartości pod tym UUID daje 409. Inny UUID tworzy osobny wpis, również gdy plik jest taki sam. Nie ma deduplikacji na podstawie samego dokumentu, ponieważ szkic i metadane mogą być inne.

Przegląd jest sekwencją dopisywanych komend: UUID komendy, oczekiwana rewizja, indeks faktu, accepted/rejected i obowiązkowa notatka. Zapis blokuje wiersz archiwum i sprawdza aktualną rewizję. Stary widok otrzymuje 409; identyczne ponowienie komendy jest idempotentne. Można zmienić wcześniejszą ocenę przez nową decyzję; historia pozostaje. Fakt odrzucony deterministycznie nie może otrzymać accepted.

`accepted` znaczy wyłącznie, że użytkownik zaakceptował szkic faktu. Nie zmienia go w obserwację available, nie tworzy raportu ani nie poświadcza jakości modelu. Weryfikujący powinien sprawdzić znaczenie metryki, kolumnę i okres, walutę, skalę, zakres konsolidacji, źródło i tożsamość emitenta. Publikacja wymaga osobnej bramki oraz kontraktu provenance.

Odczyt sprawdza zgodność bajtów, hashy, metadanych, pakietu, walidacji i ciągłości historii. Niezgodność blokuje odczyt. W tym przyroście używana jest bieżąca wersja czytnika/walidatora; przed zmianą ich semantyki potrzebna będzie jawna strategia wersjonowania i odczytu historycznych wyników.

## API i panel

- `POST /v1/panel/documents` — import lokalny i deterministyczna walidacja.
- `GET /v1/panel/documents?after_id=UUID&limit=50&instrument_id=UUID` — strona metadanych; filtr instrumentu jest opcjonalny.
- `GET /v1/panel/documents/{archive_id}` — pakiet, szkic, walidacja i historia decyzji.
- `GET /v1/panel/documents/{archive_id}/content` — oryginalne bajty do pobrania.
- `POST /v1/panel/documents/{archive_id}/reviews` — dopisanie decyzji.

Zapis wymaga dotychczasowej ochrony lokalnego panelu: zgodnego Origin, hosta localhost/127.0.0.1, JSON oraz `X-AlphaSense-Panel: 1`. Nie jest to uwierzytelnianie. Panel nadal służy do pracy lokalnej; publiczne wystawienie na VPS wymaga osobnego etapu auth/TLS.

W panelu otwórz sekcję „Szkice z dokumentów” pod istniejącym archiwum analiz, rozwiń „Dodaj dokument i szkic”, wskaż dokument i plik JSON ze szkicem, uzupełnij tytuł oraz daty. Import pozostaje lokalny i nie uruchamia analizy AI. W szczegółach sprawdź wartość, cytat i kontekst, następnie zapisz decyzję z notatką. Wartości dziesiętne są prezentowane jako dokładne ciągi znaków, bez zaokrąglania przez JavaScript Number.

Przykładowa para do lokalnej próby jest w `services/backend/tests/fixtures/document-agent.synthetic.txt` oraz `document-agent-draft.synthetic.json` w tym samym katalogu. To ręcznie przygotowana próbka syntetyczna, nie wynik analizy realnej spółki. Po odbiorze lokalna baza zawiera wpis „Syntetyczna Grupa Demo — test archiwum” z jedną decyzją testową. Importy przez obecny formularz są globalne (`instrument_id=null`); przypisanie do istniejącego instrumentu jest dostępne w kontrakcie API, a selektor w UI pozostaje do dodania.

Nierozstrzygnięta próba zachowuje UUID i żądanie w pamięci widoku. Ponowienie w tym widoku jest bezpieczne; po zamknięciu lub przeładowaniu strony najpierw sprawdź listę archiwum, aby świadomie zdecydować o osobnym imporcie.

## Odbiór

Odbiór 2026-11-10: pełna regresja **1039 Python PASS** (251,75 s), panel **34/34 PASS**, Node **9/9 PASS**, TypeScript/Vite build, Ruff, format, mypy, schematy i OpenAPI PASS. Jedno ostrzeżenie deprecacyjne Starlette/httpx, bez błędów. Niezależny przegląd nie wskazuje pozostałych blokerów. Poprawiono obsługę nieprawidłowego Unicode i uszkodzonych metadanych oraz szybkie odrzucanie downgrade przy blokadzie referencjonowanej tabeli instruments. Test wymaga SQLSTATE 55P03 i ma timeout, aby nie pomylić NOWAIT z anulowaniem oczekiwania.

Migracja została zastosowana na lokalnej bazie Docker: head `0010_document_archive`. Liczby istniejących instrumentów, raportów, przebiegów, snapshotów i zadań pozostały identyczne. Backupy publicznego schematu znajdują się w ignorowanym `.local-postgres/backups/before-document-archive-20261110T094420Z.dump` oraz `after-document-archive-20261110T095500Z.dump`; sprawdzono ich listę zawartości. Osobny test pg_dump/restore do izolowanej bazy potwierdza zachowanie oryginału, szkicu, całej decyzji, idempotentnego ponowienia i triggerów oraz dopisanie kolejnej rewizji po odtworzeniu.

Rzeczywisty lokalny odbiór na jawnie syntetycznej próbce: import i ponowienie zachowują ten sam UUID, szkic ma wartość 12500000 PLN z dokładnym cytatem, decyzja ma rewizję 1, pobrane bajty są identyczne. Po restarcie procesu panelu zapis i decyzja nadal są dostępne, `/ready` i `/panel/` zwracają 200; wcześniejszy raport GOOGL również 200. Przegląd w przeglądarce potwierdził tekst cytatu, rozwinięty kontekst i historię decyzji. Formularz importu plików nie był automatyzowany w przeglądarce; zapis i decyzję sprawdzono przez lokalne HTTP API oraz testy logiki UI.

W tym etapie nie wykonano nowych wywołań modeli ani płatnego API. Nie dodano PDF/OCR, benchmarku wielu emitentów, automatycznych zadań dokumentowych, zweryfikowanej telemetrii model/prompt/request/response ani publikacji faktów w raportach.
