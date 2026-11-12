# GPW — rozpoznanie źródeł i bramki pilota

Stan przeglądu: 2026-11-09. **Discovery, bez aktywnego adaptera GPW, notowań, predykcji lub automatycznego pobierania.** Nie zmieniono polityki providerów. Bezpłatny podgląd dokumentu w przeglądarce nie jest dowodem prawa do cyklicznego pobierania, przechowywania, przetwarzania przez model ani dalszego udostępniania z VPS. Brak potwierdzonej bezpłatnej ścieżki kończy się blokadą zakresu, bez płatnego fallbacku.

## Wynik

Możliwy do przygotowania jest wąski pilot **fundamentów jednego emitenta**, oparty na dokumentach jego oficjalnego IR, po dopuszczeniu konkretnych zasobów i sposobu użycia. Nie zidentyfikowano w tym przeglądzie kompletnego, dopuszczonego darmowego zestawu GPW OHLCV + corporate actions + historyczne uniwersum PIT. To blokuje deklarowanie gotowej analizy technicznej, backtestu i predykcji GPW. Zlecenie dla nieobsługiwanego rynku powinno zwracać czytelny status braku adaptera, bez mapowania polskiego symbolu do przypadkowego emitenta SEC.

## Źródła pierwotne i status dopuszczenia

| Zakres | Oficjalny materiał sprawdzony | Co potwierdzono | Decyzja w tym przyroście |
|---|---|---|---|
| ESPI/EBI | [KNF — obowiązki emitentów](https://www.knf.gov.pl/dla_konsumenta/kampanie_informacyjne/obowiazki_emitentow) | Raporty są publicznie rozpowszechniane przez wskazane systemy, a KNF odsyła m.in. do PAP/GPW. | Kandydat do odkrywania komunikatów; nie utożsamiać publikacji z licencją zbiorczego feedu. |
| ESPI, format raportów | [KNF — ESPI](https://www.knf.gov.pl/dla_rynku/espi) | Dokumentacja dotyczy także dostępu operatorów i przekazywania sprawozdań. Pakiety ESEF mogą zawierać ZIP i taksonomie. | Konto emitenta nie jest publicznym API badawczym. Nie rejestrowano dostępu ani konta. |
| PAP Biznes | [Oficjalny portal](https://biznes.pap.pl/) | W narzędziu odczytu strona główna ujawniła tylko iframe. | Nie potwierdzono publicznego darmowego API, quota ani praw cache/redystrybucji. Nie wymyślono endpointów. [Regulamin PAP.pl](https://www.pap.pl/regulamin) dotyczy innego wskazanego serwisu, więc nie traktować go jako zgody dla biznes.pap.pl. |
| Oficjalne pliki emitenta ORLEN | [Raporty okresowe](https://www.orlen.pl/pl/relacje-inwestorskie/raporty-i-publikacje/sprawozdania) | Publiczna strona zawiera pliki sprawozdań ZIP, dane liczbowe ZIP, prezentacje PDF i arkusze XLSX. | Preferowany kandydat do pilota fundamentów; najpierw warunki wykorzystania i identyfikacja konkretnego dokumentu. |
| Oficjalne pliki PKO BP | [Wyniki i prezentacje](https://www.pkobp.pl/relacje-inwestorskie/wyniki-finansowe-i-prezentacje/) | Publiczna lista udostępnia materiały PDF i XLSX. | Drugi kandydat; wymaga modelu metryk bankowych, a nie przeniesienia przemysłowego FCF. |
| Notowania GPW | [Dane rynkowe](https://www.gpw.pl/dane-rynkowe) i [polityka od 1.10.2026](https://www.gpw.pl/pub/GPW/files/PDF/dane_rynkowe/Polityka_dotyczaca_Danych_Rynkowych_GPW_.pdf) | Oficjalne materiały rozróżniają wykorzystanie wyświetlane i niewyświetlane oraz zasady dystrybucji. | Brak automatycznego dopuszczenia EOD, scrape lub treningu. Szczegóły poniżej. |
| Dane przetworzone GPW | [Dane przetworzone i wskaźniki](https://www.gpw.pl/dane-przetworzone-i-wskazniki) | Jest oficjalna oferta produktów; strona danych rynkowych wskazuje CSV/XLS. | Format do pobrania nie dowodzi bezpłatnej licencji ani dostępu bez umowy. |
| Indeksy GPW Benchmark | [Oficjalna strona](https://gpwbenchmark.pl/) | Strony nie udało się odczytać w tej sesji (timeout). | Nie zweryfikowano warunków użycia indeksów. Nie dopuszczono benchmarku, serii ani wag. |
| Stooq | [Oficjalna strona warunków](https://stooq.pl/t/) | Narzędzie otrzymało żądanie weryfikacji przeglądarki. | Nie obchodzono zabezpieczenia; nie potwierdzono uprawnień do automatyzacji/cache/VPS/predykcji. Brak aktywacji i brak kopiowania danych z pośrednika. |
| Kursy walut | [NBP Web API](https://api.nbp.pl/) | Udokumentowany publiczny GET, JSON/XML, HTTPS, kursy historyczne od2002, maksymalnie93 dni w jednym zapytaniu. | Użyteczny przyszły adapter FX; to nie notowania akcji. Osobne dopuszczenie zasad wykorzystania i dat dostępności przed integracją. |

### Ważna różnica w dokumentach GPW

Polityka obowiązująca od1.10.2026 opisuje dane opóźnione jako bezpłatne z zastrzeżeniem §6. Dalsza dystrybucja, także danych ze strony, wymaga umowy licencyjnej. Opłaty za dystrybucję opóźnioną dotyczą warunkowania dostępu opłatą. Jednocześnie opis marketingowy nadal wspomina roczną opłatę za dane opóźnione. Dla projektu wiążąca musi być ocena właściwej aktualnej umowy i konkretnego użycia; nie rozstrzygamy tej rozbieżności przez wybór korzystniejszego zdania. [Polityka, §2–3 i6](https://www.gpw.pl/pub/GPW/files/PDF/dane_rynkowe/Polityka_dotyczaca_Danych_Rynkowych_GPW_.pdf), [opis oferty](https://www.gpw.pl/dane-rynkowe).

Wniosek inżynierski: nie mamy jeszcze potwierdzonej bezpłatnej ścieżki automatycznego EOD/non-display i wyników pochodnych na VPS. Prywatny panel, publiczna strona, surowe pliki, wykresy i modelowe scenariusze to różne sposoby użycia. Discovery nie jest poradą prawną ani nową zgodą dostawcy.

## Minimalny pilot tożsamości

Preferowany pierwszy emitent: **ORLEN**, symbol GPW `PKN`, ISIN `PLPKN0000018`. Emitent potwierdza symbol i ISIN na [stronie akcjonariatu](https://www.orlen.pl/pl/o-firmie/o-spolce/organy-i-struktura-spolki/struktura-akcjonariatu). Oficjalne [powiadomienie o transakcji](https://www.orlen.pl/content/dam/internet/orlen/pl/en/investor-relations/regulatory-announcements/2025/20250109_Notification_MBartos.pdf.coredownload.pdf) wskazuje rynek `XWAR`. Te informacje służą sprawdzeniu mapowania, nie tworzą pełnego historycznego rejestru listingów.

PKO BP: ISIN `PLPKO0000016` i notowanie na GPW potwierdza [oficjalne FAQ](https://www.pkobp.pl/relacje-inwestorskie/faq). Nie wyprowadzamy kanonicznego symbolu z oznaczeń dostawców Bloomberg/Reuters. Przed dodaniem rekordu trzeba osobno potwierdzić symbol giełdowy i okres obowiązywania mapowania. Dla banku potrzebny jest osobny zestaw metryk i reguł interpretacji.

Rejestr docelowy powinien wiązać wewnętrzne UUID z ISIN, MIC, typem instrumentu, walutą notowania, emitentem i datami obowiązywania. Nazwa spółki, nazwa grupy, ticker i CIK nie są identyfikatorami zamiennymi. Bieżący symbol nie potwierdza symbolu ani składnika indeksu sprzed kilku lat.

## Bramy przed adapterem

| Pytanie do rozstrzygnięcia | Wymagany dowód | Zachowanie do tego czasu |
|---|---|---|
| Czy wskazane zasoby można cyklicznie pobierać i trwale zachować w prywatnej aplikacji VPS bez opłaty? | Aktualne warunki konkretnego hosta/produktu albo udokumentowana zgoda; techniczny kanał i limit. | Brak automatycznych pobrań. Publicznie dostępny link można pokazać jako odnośnik. |
| Czy wolno udostępniać surowe pliki lub pochodne wyniki innym użytkownikom? | Zakres licencji na cache, dokumenty, dane wyliczone i redystrybucję; rozdzielenie prywatnego/płatnego/publicznego panelu. | Bez publicznego eksportu i feedu. |
| Skąd EOD/OHLCV i corporate actions bez płatnego fallbacku? | Dozwolony endpoint, prawa do archiwum, korekty/splity/dywidendy, zmiany symboli, wycofane papiery, daty i wersje korekt. | Technika, backtest i predykcje GPW zablokowane. |
| Czy historyczny plik dowodzi dostępności w chwili decyzji? | Pierwotny czas publikacji, strefa, archiwum korekt i metadane komunikatu. | `available_at` co najmniej lokalny first_seen; brak cofania wiedzy do końca okresu raportowego. |
| Jak mapować IFRS/ESEF i rozszerzenia emitenta? | Wersja taksonomii, consolidated vs separate, jednostki/skala, duration/instant, segmenty, restatement i ręcznie porównane przykłady. | Bez używania parsera SEC US-GAAP do raportu GPW. Brak danych nie staje się zerem. |
| Czy plik mieści się w kontrakcie archiwum? | Zmierzony limit/typ, streaming, sumy kontrolne; dla ZIP limity dekompresji, path traversal, brak sieci podczas parsowania taksonomii/XML. | Nie zwiększać po cichu obecnego limitu1MiB ani nie wykonywać skryptów z raportu. |

## Kolejność implementacji po rozstrzygnięciu bram

1. Zaprojektować i przetestować rejestr rynku `XWAR` oraz historyczne aliasy niezależnie od dostawcy. Nie dopisywać polskich symboli do katalogu SEC.
2. Dopuścić jeden konkretny oficjalny kanał IR dla jednego rocznego raportu skonsolidowanego ORLEN; zachować oryginalne bajty, URL, hash i daty. Początkowo możliwy kontrolowany import pliku z prawem do użycia, bez deklarowania automatycznego pokrycia całej GPW.
3. Zbudować deterministyczny parser IFRS/ESEF lub jawny importer wybranej tabeli. Na syntetycznych fixture sprawdzić PLN/tys./mln, znaki, okresy, korekty i zgodność sum, potem niezależnie porównać fakty z oryginałem.
4. Wpiąć adapter do trwałych zadań jako osobny pipeline i pokazywać statusy `unsupported_market`, `source_not_admitted`, `missing_data` bez zmiany rynku lub paidfallbacku.
5. Dopiero po odrębnym dopuszczeniu cen i akcji korporacyjnych uruchomić technikę oraz kwalifikację predykcji: baseline, walk-forward/OOS, koszty zasobów, horyzont i niepewność. Brak przejścia bramki oznacza brak publikowanej predykcji.

W tej sesji wykonano przegląd oficjalnych stron przez narzędzie web, bez pobierania zbiorów do repo, bez kont, wiadomości do dostawców, zakupów i aktywacji providerów. Dokument jest wynikiem discovery; implementacja wymaga osobnego odbioru.
