# Pochodzenie rzeczywistych próbek benchmarku

Etap P4-01b2b dodaje lokalne przygotowanie i weryfikację próbek z zachowaniem oryginałów. Nie jest crawlerem, adapterem GPW ani wykonaniem benchmarku modelu. URL jest metadanymi; narzędzie nigdy go nie pobiera. Modele i polityka providerów pozostają nieaktywne w tym etapie.

## Przygotowanie

Manifest wskazuje ręcznie wybrane pliki pod własnym katalogiem, ich SHA256, HTTPSURL, first_seen_at/as_of, tytuł, lokalizację, oczekiwane fakty oraz deklarację przeglądu. Wzorzec jest w generowanym contracts/v1/document-corpus-manifest.schema.json. Rozszerzenia muszą odpowiadać formatowi; ścieżki absolutne, ucieczka poza katalog i niedozwolone rozszerzenia są odrzucane.

Próbka może zawierać cały dokument do1MiB albo dokładne, uporządkowane zakresy bajtów UTF8HTML/tekstu. Pełne źródło do16MiB służy wyłącznie lokalnej kuracji; suma źródeł do64MiB. Nie zwiększa to limitu importu dokumentu1MiB ani limitu PDF. Sumy wycinków nadal podlegają limitom istniejącego benchmarku. Nie dopisujemy liczb lub kontekstu do źródeł. Wycinek nie jest testem całego raportu.

```powershell
$env:PYTHONPATH='services/backend/src'
.venv/Scripts/python.exe scripts/prepare_document_benchmark.py --manifest PRYWATNY_KATALOG/manifest.json --output NOWY_KATALOG
.venv/Scripts/python.exe scripts/prepare_document_benchmark.py --verify NOWY_KATALOG
```

Nowy katalog zawiera sources/, excerpts/, suite.json i provenance.json. Na POSIX katalog ma0700 i pliki0600; na Windows obowiązują ACL. Nie nadpisujemy katalogów. Nieudany zapis może pozostawić niekompletny nowy katalog; verify nie potwierdzi go jako prawidłowego. Nie używaj istniejącego katalogu do ponowienia — wybierz nowy.

Weryfikacja ponownie wyprowadza wycinki z oryginałów i sprawdza modele, zakresy, metadane, gold, długości, hashe i zgodność suite. Wykrywa zmiany zachowanych plików, lecz nie jest podpisem emitenta ani dowodem prawdziwości dokumentu. Deklaracja independently_reviewed wymaga notatki; sam program nie sprawdza tożsamości recenzenta i nie promuje automatycznie draft. Przy zmianie adnotacji przygotuj nowy katalog i zachowaj stary.

Suite ma data_origin=user_supplied oraz classification=private. Nie przesyłaj go do zewnętrznego modelu bez osobnej oceny źródeł/polityki danych i dopuszczenia dostawcy. Hash źródła i publicznyURL nie są licencją na cykliczne pobieranie, redystrybucję lub zewnętrzne przetwarzanie. Artefakty rzeczywistych materiałów i gold pozostają w ignorowanym.local-postgres; nie zostały dodane doGit.

## Pierwszy zestaw rzeczywisty

Lokalny katalog .local-postgres/real-document-corpus-20261110T161011Z zawiera kopie oficjalnych materiałów. prepared-draft zachowuje wersję roboczą; prepared-reviewed jest nową wersją po niezależnym przeglądzie gold. Obie wersje są oddzielne. Próbki:

- ORLEN: nagłówek rocznej tabeli, wiersz przychodów2024/2025 i podpis o skonsolidowanym raporcie2025 ze [strony danych finansowych](https://www.orlen.pl/pl/relacje-inwestorskie/prezentacje/dane-finansowe). Dwa oczekiwane fakty odnoszą się do prezentacji porównawczej w tej wersji źródła. Nie utożsamiamy wartości2024 z jej wcześniejszą publikacją. Wycinek kończy podpis przed przypisem z dodatkowymi danymi operacyjnymi, żeby nie karać poprawnej dodatkowej ekstrakcji za niepełny gold.
- Microsoft: kontekstUSD, nagłówek rachunku wyników, przychodyFY2023–FY2025 i konsolidacja z [Annual Report2025](https://www.microsoft.com/investor/reports/ar25/). Trzy oczekiwane fakty dotyczą lat lipiec–czerwiec i milionówUSD.
- Apple: wyłącznie akapit forward-looking z [komunikatuFY2025Q4](https://www.apple.com/newsroom/2025/10/apple-reports-fourth-quarter-results/), bez liczb finansowych. To rzeczywisty przypadek wymagający abstencji, nie test pominiętych wyników finansowych Apple. Pobrany powiązany PDF miał4919649bajtów i nie został zaimportowany ponad limit1MiB.

Daty dostępności przyjęto konserwatywnie jako czas lokalnego pierwszego zapisu. Znaczniki Windows o siedmiu cyfrach części ułamkowej zaokrąglono w górę do mikrosekundy; surowy zapis dat pozostał w receipts. Nie cofamy first_seen do daty raportowej lub daty publikacji opisanej na stronie. Zestaw nie stanowi danych point-in-time do historycznego backtestu.

## Wykryte ograniczenie walidatora

Niezależny przegląd potwierdził semantykę pięciu oczekiwanych faktów i jednego przypadku abstencji. Potwierdzenie gold nie jest potwierdzeniem skuteczności parsera ani modelu. Próba ręcznego szkicu Microsoft ujawniła:

1. Obecny czytnikHTML spłaszcza sąsiednie kolumny liczb do jednego wiersza. Kontrola tokenu widzi obok inne cyfry i odrzuca poprawne cytaty jako VALUE_NOT_CITED.
2. Zapis281,724 jest dodatkowo odrzucany przez ostrożny parser separatorów jako niejednoznaczny.

Nie zmieniamy prawidłowego gold, aby uzyskać lepszy wynik. Zestaw pozostaje not_qualified_offline i nie wykonano benchmarkuGemini. Naprawa wymaga wersjonowanego czytania tabel i jawnej deklaracji zapisu liczb, z zachowaniem odtwarzalności wcześniej zapisanych dokumentów.

Aktualizacja2026-11-11: [czytnik tabelv2](TABLE_READER_V2.md) rozwiązuje tę lukę po jawnym wyborze opcji. Nowy korpus prepared-table-v2 i ręczny test kompatybilności zapisano obok wcześniejszych wersji, zachowując ich hashe. Nie jest to kwalifikacja modelu.

## Sprawdzenie

Testy obejmują ścieżki, limity, hashe, zakresy, chronologię, brak nadpisania, poufny zapis oraz wykrywanie zmian. PróbęPOSIX wykonano w kontenerzeLinux jako użytkownik10001, bez sieci i sekretów:59testówPASS, w tym symlinkescape i0700/0600. Na Windows ten sam zakres ma58PASS i1SKIP ze względu na brak uprawnienia do tworzenia symlinków. NiezależnyQA sprawdził builder/CLI i rzeczywiste wycinki; uwagi o przypisieORLEN i ograniczeniuMicrosoft zostały zachowane w nowej wersji/notatkach. Nie zmieniono bazy, źródeł automatycznych ani kluczy modeli.
