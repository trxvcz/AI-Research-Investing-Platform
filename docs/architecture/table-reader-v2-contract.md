# P4-01b2c — wersjonowane tabele i liczby

Problem: legacyHTML łączy komórki odstępami; kontrola tokenów odrzuca poprawne liczby obok innych kolumn. Pojedynczy przecinek z trzema cyframi pozostaje niejednoznaczny bez jawnego kontekstu. Nie wolno zmienić odtwarzania zapisanych pakietów i ich hashy.

DocumentPacket, DocumentArchiveCreate/Summary, BenchmarkCase oraz CorpusCase otrzymują opcjonalne reader_version='table-text-v2' i number_locale='en-US'. DomyślnieNone, pomijane przy serializacjiNone przezField(exclude_if=...). Bezopcji zachować identyczne istniejące odczyty, wyniki ihashe. Opcje dozwolone wyłącznie dlaHTML; number_locale wymaga reader_versionv2. Wersja i locale pochodzą z jawnej konfiguracji wejścia, nigdy z tekstu dokumentu lub odpowiedzi modelu. Zmianaopcji nowejanalizy/importu wymaga nowejtożsamości; nie podmieniać zapisów.

document_contracts eksportuje ReaderVersion/NumberLocale i validate_reader_options(format,reader_version,number_locale). read_text_document przyjmuje nowe opcjonalnekwargs i zwraca je wPacket. HTMLv2 zachowuje rozdzielenie komórek przezliteral ' | ', także pustych; p/div wewnątrzkomórki nie spłaszczają granic wiersza. Bezwnioskowania oheaderach/rowspanach/walucie/konsolidacji. Legacydomyślny musi być byte-identical tekstowo.

parse_value_token(token,*,number_locale=None) zachowuje dotychczasowy wynik/odmowy przyNone. en-US: comma tylko jako poprawne grupowanie3cyfr, dot jako separator dziesiętny; bezfloat, bezspacji tysięcy, bez mieszanych separatorów. Np281,724->281724,1.234->1.234,1,23odmowa. Dotychczasowa obsługa znaku/nawiasów bez zmiany. _check_fact wybiera locale zPacket po pełnej walidacji, zachowuje kontrolę całego tokenu i cytatu/skali. Nie osłabiać cytatów ani nie wycinać fragmentów liczby.

Archive_prepare/decode przekazują i utrwalają opcje; staremetadata bezpól odtwarzająlegacy z identycznymi hashami. Benchmark/corpusanalogicznie, staresyntetycznefixture i prywatnecorpus hashy muszą pozostać niezmienione. Reader/walidatorv2 musi być odrębnie wybrany; model/policy/budżet pozostają bez zmian.

Panel dla nowychimportówHTML jawnie wybiera noweczytanietabelv2 i umożliwia wybór zapisu liczb en-US lub 'niezadeklarowany' (domyślnie). Nie zgadywać locale zemitenta. Szczegółyzapisuzawierają wybrane ustawienia. Inneformaty i stary workflow bez zmiany. CLIreview_document oraz opcjonalneargumentyprzygotowania korpusu korzystają ztych samych jawnychpól.

Odbiór: starehashy/archiwumHTML bezpól niezmienione; nowyHTMLv2 3faktyMicrosoft z rzeczywistych cytatów przechodząneeds_review po en-US,bezmodelu. Brak deklaracjisemantycznejakceptacji. Testy negatywne separatorów, tokenów, HTMLhidden/limits/emptycells i konfliktuopcji/idempotencji. Nowycorpusv2 zapisaćobok starego bez nadpisania; nie aktualizować starego requestu lubsuite. Regenerować schematy/OpenAPI/typy i pełna regresja.
