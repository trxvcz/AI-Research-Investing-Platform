# Wskaźniki rentowności i przepływów

Panel otrzymuje osobną tabelę obliczanych wskaźników dla maksymalnie trzech rocznych okresów z archiwów raportu. Wskaźniki nie zmieniają istniejących raportów ani zapisanych analiz AI. Są osobną deterministyczną sekcją; obecny prompt AI nadal otrzymuje swój dotychczasowy zamrożony kontekst faktów i porównań, bez nowych wskaźników. Ich odczyt nie uruchamia Gemini ani pobierania źródeł.

- Marża netto: wynik netto / przychody ×100%.
- Marża przepływów operacyjnych: przepływy operacyjne / przychody ×100%.
- Nakłady do przychodów: nakłady na rzeczowe aktywa trwałe / przychody ×100%.
- Marża uproszczonego FCF: (przepływy operacyjne − wskazane nakłady) / przychody ×100%.

Ostatni wskaźnik jest ograniczonym porównaniem dwóch pozycji, nie pełnym przepływem dla właścicieli, wyceną lub prognozą. Nie wprowadzamy ratingów ani automatycznych ocen dobre/złe.

Wymagane są dokładnie zgodne okresy, waluta USD i ten sam niepusty identyfikator sprawozdania. Przychody muszą być dodatnie; dla wskaźników korzystających z nakładów wymagane są nieujemne nakłady. Strata lub ujemny przepływ operacyjny pozostają wartościami ujemnymi. Brak, niezgodność okresu/publikacji i niedozwolona podstawa dają jawny powód niedostępności, nigdy zero.

Kwoty wejściowe są dokładnymi ciągami dziesiętnymi. Wynik zaokrąglamy HALF_EVEN do sześciu miejsc procentowych. Każdy wynik wskazuje operandy, snapshoty, hashe i maksymalny available_at źródeł. Porównawcze kwoty mogą być przekształcone w późniejszym sprawozdaniu — nie odtwarzają wiedzy inwestora w historycznym roku.

API: GET `/v1/panel/reports/{report_id}/{revision}/financial-ratios`, tylko odczyt, no-store/nosniff. Odpowiedź wiąże dokładną rewizję i checksum oraz zawiera historię do niezależnej kontroli operandów. Frontend sprawdza tożsamość, źródła i obliczenia całkowitoliczbowe BigInt. Zakres obejmuje obsługiwane archiwa SEC; GPW wymaga odrębnego adaptera danych. Nie ma migracji, nowych zależności, płatnych wywołań ani zmian podpisanej kwalifikacji AI.

Rzeczywisty odbiór2026-11-12: API200 i walidator panelu zaakceptowały oba archiwa. GOOGL:3marże netto i9jawnych braków; AAPL:12wyników. Najnowsze wartości GOOGL:marża netto32.809878%. AAPL:marża netto26.915064%, przepływy/przychody26.788190%, nakłady/przychody3.055308%, uproszczonyFCF/przychody23.732882%. Interfejs potwierdził tabelę obu spółek i rozwinięte operandy Apple. Hashy raportów/AI i38PLN pozostałej rezerwy nie zmieniono; sygnatura kwalifikowanego kodu AI nadal zgodna.

NiezależnyQA nie wskazał pozostałych blokerów po ujednoliceniu odmowy dla pustych serii i sortowania okresów.36testów arytmetyki/modelu oraz6API PASS; panel98/98, Node9/9, TypeScript/Vite, Ruff/format, mypy84modułów, schematy/OpenAPI i pipcheckPASS. Pełna regresja PostgreSQL:1649PASS/1SKIP (symlinkWindows). Końcowe42testy wskaźników/API uruchomiono ponownie po dodaniu10przypadków, których nie obejmowała wcześniejsza kolekcja pełnego przebiegu.
