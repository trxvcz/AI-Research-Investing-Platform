# Analiza AI z historią — 2026-11-12

W panelu wybierz GOOGL lub AAPL i najnowszy zakończony raport. Sekcja **Analiza AI** otwiera zapisaną **Analizę z historią**. Przy trendzie widać obie wartości, okresy, zmianę kwotową i dopuszczalny procent. **Sprawdź przypisane dane** pokazuje źródła. Lista **Zapisane analizy AI** pozwala wrócić do wcześniejszej narracji bez historii. Odczyt nie wywołuje modelu.

Nowy, jawny przycisk generowania tworzy `report-history-v2` dla obsługiwanych raportów publicznych SEC. Rozwiązanie zależy od dostępnych danych i metryk, nie osobnych parserów dla symboli. W tym odbiorze użyto wyłącznie istniejących archiwów, bez pobrań SEC. GOOGL ma przychód i wynik netto; AAPL dodatkowo przepływy operacyjne i nakłady. Dostępne szeregi obejmują trzy okresy 2023–2025.

Kontekst zawiera dokładne wartości dziesiętne, okresy, pochodzenie, dostępność i wyliczone porównania. Jest zapisany wraz z analizą, identyfikatorem rewizji, sumą raportu i SHA-256. Odświeżenie tabeli historii nie przepisuje dowodów wcześniejszej analizy. Trend musi cytować jedno porównanie i właściwy kierunek. Luki oraz nieporównywalne okresy blokują zmianę; niedodatnia baza blokuje procent. Braki nie są zerami. Dane porównawcze mogą być przekształcone w późniejszym sprawozdaniu; nie odtwarzają wiedzy inwestora z dawnego roku.

Migracja0016 zachowuje stare narracje v1, raporty, audyt i wspólny limit. PostgreSQL blokuje podmianę kontekstu. API samodzielnie buduje go z oryginałów wskazanych w raporcie, bez przyjmowania dowodów od klienta. Panel weryfikuje strukturę, powiązanie z raportem, arytmetykę i SHA-256 przez Web Crypto.

## Koszt i zakres danych

Pozostaje zatwierdzony limit **50 PLN łącznie, bez odnowienia**. Każda nowa próba rezerwuje1PLN przed wywołaniem, także kwalifikacja i błędy. Ten etap wykonał6wywołań:4syntetyczne i2rzeczywiste; z wcześniejszymi próbami zarezerwowano12PLN, zostało38PLN. To konserwatywne rezerwacje aplikacji, nie rzeczywista faktura ani limit użycia klucza poza aplikacją. Ten sam UUID odczytuje istniejący wynik. Nie ma automatycznych generacji, retry, płatnych fallbacków ani resetu budżetu.

Przejrzano ponownie oficjalny cennik i warunki2026-11-12. Konfiguracja przeglądu wygasa po24h i blokuje nowe generowanie do odnowienia; zapisane wyniki nadal można czytać. Model pozostaje `gemini-3.1-flash-lite`, request32768B, wyjście2048tokenów. Do dostawcy trafiają wyłącznie znormalizowane publiczne fakty SEC i wyliczenia. Bez sekretów, prywatnych dokumentów, surowych plików, narzędzi i grounding. Zasada darmowych źródeł pozostaje; zgoda Paid dotyczy syntezy raportów.

## Odbiór i ograniczenia

Cztery zamrożone scenariusze syntetyczne przeszły walidację i niezależny przegląd: wzrost, niedodatnia baza bez procentu, luka z instrukcją atakującą oraz zakres części długu długoterminowego. Rzeczywiste GOOGL i AAPL również przeszły przegląd kierunków i cytowań. Powtórzenie ich UUID nie zużyło kolejnej rezerwacji, a wcześniejsze odpowiedzi pozostały identyczne. Panel pokazał rzeczywisty nowy wynik GOOGL i rozwinięte dowody porównania.

To ograniczona kwalifikacja prywatnego pilota. Narracje są krótkie i opisowe. Obecność gotówki nie dowodzi mocnej płynności, wzrost nakładów sam w sobie nie dowodzi ryzyka. Jedna próbka syntetyczna zawęziła ogólne revenue do przychodów ze sprzedaży. Pełna wycena, przyczyny zmian, predykcje, GPW, ekstrakcja dowolnych dokumentów i wdrożenie Oracle pozostają osobnymi etapami.

Pełna regresja PostgreSQL:1617PASS,1SKIP z powodu niedostępnych symlinków Windows. Panel89/89, Node9/9, TypeScript/Vite, schematy/OpenAPI, Ruff i mypy82modułów PASS. Testy magazynu obejmują rzeczywisty backup/restore v1 i v2. Przegląd bezpieczeństwa objął granice danych, niezmienność, źródła, odporność na instrukcje w danych, limit i brak automatycznych wywołań.

Po restarcie potwierdzono niezmienione oba raporty, wcześniejsze i nowe analizy oraz38PLN pozostałej rezerwy; zapisano nową kopię PostgreSQL. Kod panelu zaakceptował rzeczywiste odpowiedzi v1/v2 obu spółek, w tym SHA-256. SECworker, dokumenty i scheduler mają status online; nie uruchomiono nowych zadań.
