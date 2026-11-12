# Wersjonowane czytanie tabel HTML

Etap P4-01b2c rozwiązuje problem ujawniony przez rzeczywistą tabelę Microsoftu: wcześniejszy czytnik sklejał sąsiednie kolumny odstępami, a ostrożna walidacja traktowała przecinek z trzema cyframi jako niejednoznaczny. Nowe zachowanie jest jawnie wybierane i zapisywane z dokumentem. Nie zmienia odtwarzania starszych archiwów ani uruchamiania modeli.

## Użycie

Nowy import HTML w panelu zachowuje granice komórek jako tekstowe separatory ` | `, także dla pustych komórek. Wybierz zapis liczb:

- Niezadeklarowany: dotychczasowa ostrożna interpretacja, np. pojedyncze `1,234` pozostaje odrzucone.
- en-US: przecinek grupuje tysiące, a kropka oddziela część dziesiętną. `281,724` oznacza281724, `1,234.50` oznacza1234.50, a `1.234` oznacza1.234. Złe grupowanie, np. `1,23`, jest odrzucane.

Nie zgadujemy zapisu liczb na podstawie spółki lub instrukcji w dokumencie. Ustawienie powinno wynikać z ręcznie sprawdzonego źródła. Nowy szkic musi cytować bloki wersji, w której ma być walidowany; zmiana ustawień może zmienić bloki i wymaga nowego importu. Szczegóły dokumentu pokazują zapisany wariant odczytu i liczb.

CLI:

```powershell
$env:PYTHONPATH='services/backend/src'
.venv/Scripts/python.exe scripts/review_document.py PLIK.html --format html --reader-version table-text-v2 --number-locale en-US
```

Inspect pozostaje lokalny i zwraca model_called=false. Jawne opcje mają inną tożsamość pakietuCLI niż odczyt legacy tych samych bajtów. Tryb --draft sprawdza zapisany szkic bez wywołania modelu. API, benchmark i manifest korpusu przyjmują opcjonalne reader_version=`table-text-v2` oraz number_locale=`en-US`. Locale wymaga wersji v2; oba ustawienia są obecnie dozwolone wyłącznie dlaHTML. PDF iXLSX zachowują wcześniejszy zakres.

## Zgodność historii

Brak nowych pól wybiera wcześniejsze zachowanie. Wartości None nie trafiają do serializacji, więc stare requesty, pakiety i zestawy zachowują hashe. Archiwum utrwala opcje w nowym zapisie i odtwarza dokładnie ten wybór przy odczycie. Próba zmiany opcji istniejącego UUID kończy się konfliktem. Kolejka offline i fingerprint wykonawcy uwzględniają istniejące powiązania pakietu/kodu. Nie ma migracji bazy ani podmiany wcześniejszych raportów.

Separator komórek poprawia kontrolę całego tokenu, lecz nie dowodzi poprawnej interpretacji nagłówków, rowspanów, okresów, waluty lub konsolidacji. Kontrola cytatu i skali nadal obowiązuje, a wynik poprawnego kandydata to needs_review. Model nie może dodać locale do faktu i sam zmienić reguł. Treść źródła pozostaje danymi, nie instrukcją.

## Odbiór na zachowanych źródłach

Obok wcześniejszych katalogów prepared-draft i prepared-reviewed zapisano nowy prepared-table-v2 w prywatnym.local-postgres/real-document-corpus-20261110T161011Z. Stary korpus został ponownie zweryfikowany z niezmienionym hashem. Nowy wybiera v2 dlaHTML, a en-US wyłącznie dla sprawdzonej tabeli Microsoftu; gold i oryginalne bajty nie zostały poprawione pod wynik.

Ręcznie przygotowany test kompatybilności obejmuje pięć prawidłowych faktów ORLEN/Microsoft i jeden fragmentApple wymagający abstencji. Po wybraniu właściwych opcji uzyskano5TP/0FP/0FN i1poprawną abstencję; wszystkie wspierane kandydatury wymagają nadal przeglądu semantycznego. To kontrola czytnika na ręcznych odpowiedziach, nie pomiar jakościGemini. Raport pozostaje hand_authored_reference i not_qualified_offline, bez wywołania modelu.

Po przerwie wznowiono istniejący Docker i bazę. Ujawnione w diagnostyce błędu lokalne poświadczenie zostało unieważnione po osobnej zgodzie właściciela; nowe logowanie działa, poprzednie jest odrzucane. Zaktualizowano pasujące ignorowane konfiguracje i odświeżono lokalne usługi. W testach użyto skróconych diagnostyk, bez wypisywania sekretów. Nie zmieniano kluczy modeli, polityki providerów ani zasobów chmurowych.

Odbiór2026-11-11:1443testyPythonPASS w jednym pełnym przebiegu(229,40s),1SKIP dotyczący tworzenia symlinków naWindows; osobno2/2nowe testyCLI tożsamości/opcjiPASS. Panel56/56, Node9/9 i TypeScript/VitebuildPASS. Linux43/43testówczytnikav2PASS w kontenerze bez sieci i sekretów. Ruff/format/mypy i zgodność schematów/OpenAPIPASS. Znane ostrzeżenieStarlette/httpx pozostaje. Końcowy przegląd v2 wykonał koordynator po wyczerpaniu limitu podagenta, bez deklaracji niezależnegoQAtejpoprawki. Poprzedni niezależny przegląd korpusu potwierdził gold. /ready i wcześniejszy raportGOOGL zwracają200, trzy rodzaje wykonawców mają aktualny heartbeat. Nie wykonywano wizualnego odbioru formularza; logikę opcji/ponowień sprawdzono testami panelu, a trwałość archiwum i kolejki na izolowanych schematachPostgreSQL.
