# Darmowy model do wspólnego agenta dokumentów

Stan przeglądu: 2026-11-09. Użytkownik wybrał darmowy model zewnętrzny i wskazał posiadanie Gemini API. **Adaptery są przygotowane, ale dostawca modelu nie został aktywowany w `provider-policy.json`. Nie wykonano rzeczywistych wywołań ani przesłania dokumentów.**

## Wybrany kierunek — Gemini Developer API

[Oficjalny cennik](https://ai.google.dev/gemini-api/docs/pricing) rozróżnia bezpłatny i płatny zakres poszczególnych modeli oraz osobne funkcje. Bezpłatność jednego modelu nie oznacza darmowych wyszukiwań, plików, cache lub innych narzędzi. Nasz adapter wykonuje wyłącznie `generateContent` z tekstem i odpowiedzią JSON; nie uruchamia wyszukiwarki, kodu, narzędzi, przechowywania plików ani płatnego fallbacku.

[Limity](https://ai.google.dev/gemini-api/docs/rate-limits) są zależne od modelu, projektu i poziomu konta. Dokładne wartości trzeba odczytać w AI Studio dla użytego klucza. Nie przepisujemy historycznych limitów z artykułów i nie traktujemy lokalnego limitu prób jako gwarancji braku naliczenia po stronie dostawcy. Przed aktywacją trzeba potwierdzić bezpłatny poziom projektu i brak możliwości automatycznego wejścia w płatne użycie. Projekt z aktywnym billingiem nie staje się bezpłatny przez ustawienie budżetu w naszej aplikacji.

Polityka danych wymaga osobnej oceny. Tabela cen opisuje wykorzystanie danych w bezpłatnym zakresie do ulepszania produktów, ale [warunki Gemini API](https://ai.google.dev/gemini-api/terms) zawierają wyjątek dla EOG, Szwajcarii i Wielkiej Brytanii: warunki wykorzystania danych właściwe dla usług płatnych mają tam zastosowanie również do bezpłatnych usług. Nie należy przypisywać ogólnej reguły z tabeli automatycznie polskiemu użytkownikowi. Przed uruchomieniem należy potwierdzić właściwy podmiot i zakres aktualnych warunków. Pierwszy pilot powinien używać wyłącznie dopuszczonych publicznych dokumentów, bez sekretów, notatek prywatnych i danych osobowych. Nasza bramka `public_only` blokuje przesyłanie materiałów sklasyfikowanych jako prywatne lub tajne.

Nie wybrano domyślnego modelu w kodzie. `GeminiTransport(model_id=...)` wymaga identyfikatora z zaufanej konfiguracji serwera, osobno zatwierdzonego dla tego projektu, bezpłatnego zakresu i zadania. [Oficjalna lista Firebase](https://firebase.google.com/docs/ai-logic/models) wskazuje zakończenie obsługi Gemini 2.5 Flash-Lite w październiku 2026; historyczna popularność nie uzasadnia przypięcia tego modelu w listopadzie. Dostępność, limity i jakość aktualnego kandydata wymagają potwierdzenia przed aktywacją.

## Alternatywa — Groq Free

[Billing FAQ Groq](https://console.groq.com/docs/billing-faqs) rozróżnia Free i płatny Developer; przejście na Developer wymaga metody płatności. [Aktualne limity](https://console.groq.com/docs/rate-limits) są organizacyjne, obejmują m.in. żądania i tokeny, a dokładne wartości są w ustawieniach konta. Publiczna tabela nie jest dowodem limitu naszego konta; jej opis odnosi się także do planu Developer. Starszy wpis społeczności o braku naliczeń po przekroczeniu Free obecnie przekierowuje do strony głównej, więc nie służy jako samodzielny dowód twardej blokady naliczania.

[Dokumentacja danych Groq](https://console.groq.com/docs/your-data) opisuje brak domyślnego zachowywania treści zwykłej inferencji, ale przewiduje wyjątki operacyjne i bezpieczeństwa oraz zawsze zachowywane metadane użycia. Nie obiecujemy absolutnego braku retencji. [Tryb JSON](https://console.groq.com/docs/structured-outputs) nie gwarantuje prawdziwości faktów; nawet poprawny JSON musi przejść walidację dowodów. `GroqTransport` pozostaje nieaktywną alternatywą, bez automatycznego przełączania po błędzie Gemini.

## Gotowy zakres techniczny i bramki aktywacji

Oba transporty przyjmują ten sam wewnętrzny pakiet dwóch wiadomości: system i użytkownik. Model i parametry sieciowe pochodzą z konstruktora serwerowego, a dokument nie może nadpisać endpointu, modelu, narzędzi ani klucza. TLS jest weryfikowany. Jest jeden ustalony host i endpoint, bez proxy środowiskowych, przekierowań i ponowień po 429 lub błędzie. Limit treści żądania to 3 MiB, odpowiedzi 256 KiB, a limit generowanych tokenów jest jawny i ograniczony. Odpowiedź ucięta lub żądająca narzędzia nie jest przyjmowana jako szkic.

Klucz Gemini należy ustawić jako `GEMINI_API_KEY` (alternatywnie `GOOGLE_API_KEY`) w środowisku procesu serwera/wykonawcy. Nie wklejać klucza do czatu, plików śledzonych w Git, formularza dokumentu ani URL. Adapter przekazuje go wyłącznie nagłówkiem `x-goog-api-key`. Alternatywa Groq odczytuje tylko `GROQ_API_KEY`. Kod i testy nie wykrywają ani nie ujawniają wartości kluczy.

Przed rejestracją adaptera w istniejącym `FreeOnlyGateway` muszą być spełnione wszystkie bramki:

1. Serwerowa, aktualna ocena warunków i klasyfikacji przesyłanych dokumentów.
2. Potwierdzenie konkretnego modelu i projektu w bezpłatnym zakresie oraz twardej blokady opłat; brak potwierdzenia oznacza odmowę.
3. Zmierzony próg jakości na zestawie dokumentów różnych emitentów, języków i układów, w tym mylące kolumny okresów i skale PLN/tys./mln.
4. Wpis `ProviderGrant` z `max_charge_usd=0`, bez fallbacku, z dowodem przeglądu, datą ważności i trwałą quota PostgreSQL. Żaden z tych dowodów nie pochodzi z odpowiedzi modelu lub dokumentu.
5. Walidacja dowodów i jawny status szkicu wymagającego przeglądu. Transport nie publikuje `ResearchInput`, raportu końcowego ani predykcji.

W tym przyroście sprawdzono transporty na syntetycznych odpowiedziach HTTPS. Nie ma deklaracji wyniku benchmarku modelu ani gotowego pokrycia dowolnego raportu. Uszkodzony, zeskanowany lub nieobsługiwany dokument może wymagać OCR albo zwrócić brak danych.
