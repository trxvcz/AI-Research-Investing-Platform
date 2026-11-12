# ORLEN — ocena konkretnego źródła fundamentów

Stan: 2026-11-09. **Źródło nieaktywne w provider-policy; rekomendowany ograniczony pilot prywatny.** Dokument doprecyzowuje GPW_DISCOVERY.md. Nie utworzono adaptera, raportu ani predykcji, nie zapisano zbioru finansowego do archiwum aplikacji.

## Konkretny zasób

Oficjalna strona [Dane finansowe ORLEN](https://www.orlen.pl/pl/relacje-inwestorskie/prezentacje/dane-finansowe) ma tabelę roczną 2024/2025, opisaną jako MSSF i mln zł. Wskazuje skonsolidowany raport roczny Grupy ORLEN za2025 oraz datę publikacji29 kwietnia2026. To podstawa wyboru kontekstu consolidated/IFRS/PLN; nie jest dowodem historycznej dostępności aktualnych bajtów pliku.

Przycisk pobrania danych rocznych prowadzi do konkretnego [Raport_roczny_2025.xlsx](https://www.orlen.pl/content/dam/internet/orlen/pl/pl/relacje-inwestorskie/informacje-finansowe/dokumenty/Raport_roczny_2025.xlsx). Narzędzie web potwierdziło adres i MIME XLSX, lecz nie odczytało zawartości arkusza. Rozmiar w bajtach, SHA256, arkusze, zakresy komórek, formuły i wewnętrzne jednostki pozostają **niezweryfikowane**. Nie zakładamy, że plik mieści się w limicie archiwum1MiB.

Dla porównania bieżąca strona [Raporty okresowe](https://www.orlen.pl/pl/relacje-inwestorskie/raporty-i-publikacje/sprawozdania) wskazuje kwartalny [Dane_ze_sprawozdania_3Q2026.zip.coredownload.zip](https://www.orlen.pl/content/dam/internet/orlen/pl/pl/relacje-inwestorskie/raporty-i-publikacje/sprawozdania/2026/3q2026/Dane_ze_sprawozdania_3Q2026.zip.coredownload.zip), opisany przez witrynę jako69KB. To rozmiar deklarowany, nie pomiar pobranych bajtów. Jest to kwartał, a nie zamiennik rocznego raportu2025. Format ZIP wymaga oddzielnych limitów dekompresji i kontroli ścieżek.

Odczyty stron oraz bezpośrednie linki nie wymagały konta lub płatności. Nie potwierdzono jednak API, SLA ani limitu automatycznych zapytań. Brak opłaty przy odczycie nie rozstrzyga licencji wykorzystania.

## Warunki zamiast domysłów

[Zastrzeżenia prawne ORLEN](https://www.orlen.pl/pl/zastrzezenia-prawne) rozdzielają dwie sytuacje:

- Dopuszczają pobieranie i drukowanie stron lub fragmentów pod warunkiem poszanowania praw autorskich i znaków.
- Wykorzystanie komercyjne, obejmujące m.in. kopiowanie, elektroniczne przekazywanie lub modyfikowanie treści, uzależniają od uprzedniej pisemnej zgody ORLEN.

To **konkretne ograniczenie** dla komercyjnego wariantu platformy. Nie jest poprawne stwierdzenie, że brak publicznego API sam w sobie zakazuje automatyzacji. Przeczytany tekst nie opisuje jednoznacznie prywatnego, niekomercyjnego cyklicznego GET, trwałego cache, ekstrakcji faktów lub przetwarzania przez modele. Nie wyprowadzamy z tego milczenia ani generalnego zakazu, ani pełnej licencji. Sam fakt uruchomienia na VPS nie przesądza komercyjności, lecz publiczne udostępnianie/monetyzacja wymaga odrębnej oceny. Należy też rozdzielić prawa do pliku, jego układu i tekstów od statusu pojedynczych faktów liczbowych. Nie stwierdzamy, że sama liczba finansowa automatycznie jest chronionym utworem; ekstrakcja faktów nie daje jednak automatycznie zgody na kopiowanie całego pliku, zbioru lub jego dalszą dystrybucję.

Adres [robots.txt](https://www.orlen.pl/robots.txt) był niedostępny w narzędziu web. Dodatkowa próba weryfikowanego HTTPS do robots i HEAD pliku XLSX zakończyła się błędem zaufania łańcucha certyfikatów w lokalnym środowisku. Nie wyłączano walidacji TLS, nie obchodzono zabezpieczeń i nie traktujemy nieudanego odczytu jako dowodu disallow lub allow. Robots jest wskazówką techniczną, a nie samodzielną licencją danych.

## Decyzja dla projektu

Użytkownik potwierdził w tej sesji: **VPS wyłącznie do prywatnego, osobistego użytku, bez udostępniania innym i monetyzacji**. To przyjęty zakres projektu, nie zgoda na wariant publiczny.

Dla tak określonego pilota rekomenduję dopuścić po technicznym przeglądzie **jednorazowy, jawnie wywołany GET dokładnego pliku Raport_roczny_2025.xlsx, zachowanie lokalnej kopii wyłącznie w prywatnym archiwum oraz deterministyczny odczyt wybranych faktów do prywatnego raportu**. Podstawą jest pozytywne postanowienie ORLEN o pobieraniu, przy odrębnie opisanym ograniczeniu zastosowań komercyjnych. Nie ma podstaw, aby blokować ten osobisty pilot wyłącznie z powodu braku publicznego API. Nie jest to rekomendacja cyklicznego crawlowania, pobrania całego zbioru ani trenowania modelu na dokumentach.

Przed aktywacją konkretnego GET pozostają techniczne bramki: poprawnie weryfikowany TLS, pomiar rozmiaru i hash, ograniczenie wielkości oraz bezpieczny parser XLSX. Przyjęty limit aplikacyjny może wynosić jedno jawne pobranie wskazanego pliku, bez automatycznych ponowień; nie należy przedstawiać go jako limitu ogłoszonego przez ORLEN. `robots.txt` nadal ma status niezweryfikowany, bez domniemania zakazu lub zezwolenia. Tej rekomendacji nie zapisano do provider-policy i pliku nie pobrano w ramach tej pracy.

Dla ewentualnego przyszłego wariantu komercyjnego blokadą pozostaje wskazany warunek zgody. Nie wysyłano zapytań do emitenta ani nie tworzono kont.

Można już projektować deterministyczny importer XLSX na syntetycznych fixture: ścisły zakres arkusza/komórek, kontrola consolidated/standalone, waluty i skali, duration/instant, pustych pól, korekt i dat. Importer nie może wykonywać makr, formuł, zewnętrznych linków ani pobierać dalszych dokumentów na polecenie pliku.

Przed rzeczywistym pilotem:

1. Zachować potwierdzony osobisty zakres VPS. Przy zmianie na wariant publiczny/komercyjny ponownie przejrzeć warunki i uzyskać wymagany zakres praw albo wybrać inne dopuszczone źródło.
2. Potwierdzić techniczne zasady dostępu i prawidłowy TLS. Jawnie ustalić częstotliwość i limit, bez skanowania całej witryny.
3. Jednorazowo pobrać dopuszczony plik, zachować dokładne bajty, SHA256 i first_seen; zmierzyć rozmiar i zbadać strukturę XLSX. Datę publikacji traktować osobno od lokalnej dostępności bajtów.
4. Porównać wybrane fakty z rocznym sprawozdaniem grupy i zamrozić wersjonowane mapowanie IFRS/PLN. Ta ścieżka nie dostarcza cen akcji, corporate actions ani predykcji GPW.

## Weryfikacja prac

Odczytano oficjalne strony i ich konkretne odnośniki, bez aktywacji providera, ingestii zbioru, zakupów, kontaktowania emitenta i nowych uprawnień. Wyłącznym plikiem tej pracy jest ten dokument.

## Weryfikacja techniczna koordynatora2026-11-09

Po zgłoszonym problemie lokalnego łańcucha certyfikatów wykonano weryfikowany HTTPS HEAD przez systemowy stos Windows, bez wyłączania TLS i bez przekierowań:200, Content-Length13143, Content-Type application/vnd.openxmlformats-officedocument.spreadsheetml.sheet. GET robots.txt zwrócił User-agent:* oraz puste Disallow. Nie jest to licencja, ale usuwa wcześniejszą niepewność techniczną tego odczytu. Nie pobrano jeszcze danych finansowych do runtime.

Użytkownik jawnie potwierdził prywatny research wyłącznie dla siebie. Rekomendowany następny przyrost to jednorazowe pobranie wskazanego XLSX i bezpieczny parser ustalonych komórek IFRS/PLN po weryfikacji zawartości, bez crawlera i bez redystrybucji. Predykcje i notowania nadal wymagają oddzielnego dopuszczenia źródła.
