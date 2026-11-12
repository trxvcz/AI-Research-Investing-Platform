# P4-01b2d — ograniczona kwalifikacja developerska Gemini Free

Decyzja właściciela2026-11-11: projektFree, wyłączonybilling i potwierdzenie, że obecny klucz.env należy do tego projektu. Nie jest to zgoda naPaid, zmianę rozliczeń lub wysłanie prywatnego korpusu. models.list200 potwierdza dostępność gemini-3.1-flash-lite, nie dowodzi poziomu rozliczeń. Dowodem konta jest potwierdzenie właściciela powiązane lokalnie hashem klucza. Nie wypisywać klucza.

Zakres pierwszego pomiaru: dokładnie8przypadków syntetycznego suite osha933e6b64ff63d09a0e7b90bbf72287b462ab6c02144cdbd09fb5b58ad3f3154a. Tylko public/synthetic, bez realnego korpusu, notatek,URLdo pobrania lub gold wpromptach. Istniejący wspólnyprompt document-facts-v1 budowany przez build_document_request. Domyślne etykiety metryk i walidatory bez dostrajania na odpowiedziach. Brak narzędzi, grounding, kodu, plikówAPI i cache dostawcy.

Model gemini-3.1-flash-lite: przegląd oficjalnej tabeliStandard2026-11-11 potwierdza free input/output. Obecne dokumentybilling pozwalająFreewEOG, warunki opisują osobno udostępnianieAPIclients i zasady danych. Ten test jest własnym testem developerskimCLI, bez udostępnienia klienta innym użytkownikom. Przed produkcyjną integracją trzeba rozstrzygnąć właściwe warunki dla docelowej aplikacji. Nie włączamy stałego grantu ani workera modelowego.

Limit: najwyżej8prób generateContent,1próba/przypadek, bezretry/fallbacku. Odstęp co najmniej15s po poprzednim wywołaniu, maxOutputTokens4096, temperature0, request/response limits zGeminiTransport. Atomowa rezerwacja prób w istniejącymPostgreSQLQuotaStore przed każdą siecią. Osobny scope i krótki termin ważności, brak zwrotów quota. Stop po pierwszym błędzie HTTP/transportu, także429; nie zmieniać konta/modelu po odmowie. WarunekFree/wyłączonybilling sprawdzony przed generacją i niezmienny hashklucza wczasie pomiaru.

To jawna ścieżka kwalifikacyjna przed bramką jakości produkcyjnej; quality_pass pozostajeFalse w opisie grantu ewaluacyjnego. Nie podstawiać fikcyjnegoTrue. ProdukcyjnyFreeOnlyGateway nadal wymagaquality_pass i jego warunki nie są zmieniane. Jednorazowy kwalifikacyjnyCLI korzysta z zatwierdzonego protokołu, ręcznie sprawdzonegoFree/terms/data i trwałejquota; nie jest dostępnymAPIprodukcji.

Zamrożony syntetyczny próg kontrolny: dokładne7TP,0FP,0FN,0invalid_responses,2successful_abstentions/2. Brak zmiany gold lub promptu pomiędzy przypadkami. Niespełnienie progu jest wynikiem, nie powodem ponowień. NawetPASS nie kwalifikuje rzeczywistych dokumentów lub produkcji; wynikBenchmarkResult pozostaje not_qualified_offline. Niepełny pomiar nie dostaje metryk obejmujących wyłącznie łatwiejsze ukończone przypadki.

Audyt lokalny w ignorowanym katalogu0700: konto/przegląd, protokół ihashe, request/prompthash, model_id/prompt_version, surowa odpowiedź i jejhash, szkic, walidacja, statusHTTP/finishReason/modelVersion/usagejeśli występują, czas oraz rezerwacjaprzedwywołaniem. Brakujące usage jestnull, nie0. Żadnych nagłówkówAuth,kluczy lub URLzkluczem. Pliki wyników wyłącznie nowo tworzone. To developerski audyt, nie migracja kolejki lub produkcyjna telemetriaLLM.

Po8odpowiedziach istniejący evaluator porównuje wynik z całymzamrożonymgold. Po błędzie zachowuje partialaudit i niczego nie publikuje. Raport opisuje rzeczywiściezmierzone fakty, bez twierdzeń o zerowej fakturze na podstawie samegoHTTP200.
