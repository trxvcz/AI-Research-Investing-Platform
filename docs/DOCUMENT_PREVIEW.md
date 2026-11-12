# Podgląd dokumentu bez szkicu JSON

Etap P4-01c2d pozwala sprawdzić, co wspólny czytnik odczyta z pliku, zanim przygotujesz szkic lub zapiszesz go w archiwum. Podgląd nie wymaga pliku szkicu, tytułu i dat importu ani działającej bazy danych. Nie wywołuje modelu i nie tworzy dokumentu, zadania lub raportu w bazie.

## W panelu

1. Otwórz „Szkice z dokumentów” → „Dodaj dokument i szkic”.
2. Wybierz dokument źródłowy i format. DlaHTML sprawdź wybrane reguły liczb; klasyfikacja domyślnie pozostaje prywatna.
3. Kliknij „Podejrzyj dokument bez szkicu”.
4. Rozwijaj bloki, sprawdzając tekst, block_id i lokalizator. Dostępne są sumy kontrolne, długość oryginału i ustawienia czytnika.

Widać początkowo do20bloków; kolejne odsłania przycisk. Tekst jest wyświetlany jako tekst, także gdy zawieraHTML lub instrukcje. Nie wykonujemy go i nie zamieniamy adresów na automatycznie pobierane zasoby.

Zmiana pliku, formatu, klasyfikacji lub reguł liczb unieważnia podgląd. Odpowiedź jest związana zUUID żądania, SHA256 oryginału, długością i ustawieniami. Generacja żądania i porównanie bieżącego wyboru blokują wyświetlenie spóźnionej odpowiedzi poprzedniego pliku. Przycisk „Wyczyść podgląd” przerywa oczekiwanie i usuwa wynik z pamięci widoku. Wybrany plik pozostaje dostępny do późniejszego importu; nie deklarujemy zerowania pamięci przeglądarki/systemu.

Podgląd nie tworzy szkicu faktów. Zapis do archiwum nadal wymaga osobnego szkicuJSON, tytułu i dat. Cytaty powinny odnosić się do bloków dokładnie tych samych bajtów i ustawień odczytu. Bloki mają inną tożsamość dokumentu w zapisie archiwalnym, ale ich block_id/tekst/lokalizatory są deterministyczne dla tego samego odczytu.

## Ograniczenia

Limit oryginału1MiB; limity512bloków/2MiBtekstu i ograniczenia istniejących czytników pozostają bez zmiany. Obsługiwane są UTF8tekst, statycznyHTML, XLSX bez formuł i tekstowyPDF. PDF nie dodajeOCR i wymaga tekstu na każdej stronie. Układ tabel, ukrycie tekstu przezCSS, znaczenie okresów i walut nadal wymagają porównania z oryginałem.

Podgląd jest uruchamiany tylko przyciskiem. Nie ma automatycznych wywołań, retry, pollingu ani zapisu do localStorage/sessionStorage. Klient przerywa oczekiwanie po30s; anulowanieHTTP nie jest gwarancją natychmiastowego zatrzymania krótkiego odczytu serwerowego. CzytnikPDF ma własny limit czasu/pamięci. Serwer nie zapisuje podglądu, a odpowiedź ma no-store. Dotychczasowe archiwum i modele pozostają osobnymi funkcjami.

## API

POST /v1/panel/document-preview przyjmuje DocumentPreviewCreate: document_idUUID,format,classification,content_base64 oraz opcjonalne ustawieniaHTMLv2. Zwraca packet,byte_length,model_called=false,persisted=false. SourceURL i szkic nie są akceptowane. Schematy są generowane zPydantic w contracts/v1/document-preview-*.schema.json oraz OpenAPI.

ZapisHTTP wymaga Origin, JSON i X-AlphaSense-Panel:1 zgodnie ze wspólną białą listą. Na prywatnym hoście wymagane jest również dotychczasowe logowanie dla każdej ścieżki. Body jest ograniczone do4MiB przed parsowaniemJSON; canonicalbase64 i rozmiar oryginału sprawdzane ponownie przed odczytem. OdpowiedźJSON ma no-store/no-cache/nosniff. Błędy nie zwracają źródła lub ścieżek. Nie powstaje endpoint pobierający URL ani uruchamiający dostawcę.

## Weryfikacja

Testy obejmują cztery formaty, zgodność z czytnikiem archiwum, brak zależności od bazy/providerów, odrzucenie nadmiarowego szkicu/URL, Origin, prywatneauth, canonicalbase64 oraz limit strumienia zroot_path. Testy panelu sprawdzają tożsamość bajtów/opcji, błędne bloki i unieważnienie po zmianie wyboru. Rzeczywisty lokalnyPOST zwrócił200, zgodnyhash i zachowane kolumnyHTMLv2; liczniki archiwum, zadań i raportów przed/po pozostały identyczne. /ready nadal200.

Nie wykonywano benchmarkuGemini, zmian polityki danych ani wdrożeniaVPS. Nie dodano automatycznej ekstrakcji LLM. Końcowy przegląd wykonuje koordynator po wcześniejszym limicie podagenta.

Końcowy odbiór2026-11-11:1464PythonPASS w jednym końcowym przebiegu(211,52s),1SKIP dotyczący symlinków naWindows; panel61/61, Node9/9 i TypeScript/VitebuildPASS. OdizolowanyLinux:19/19testówpodgląduPASS bezsieci, bazy i sekretów. Ruff/format/mypy i zgodność schematów/OpenAPIPASS. Pozostaje znane ostrzeżenieStarlette/httpx. Pierwszy pełny przebieg wskazał nieaktualną listę ścieżek w teścieOpenAPI; po jej uzupełnieniu cały końcowy przebieg przeszedł. Panel i wcześniejszy raportGOOGL zwracają200, trzy role wykonawców pozostają online. Nie wykonywano wizualnego odbioru formularza; zachowanie danych i brak zapisu potwierdzono przezHTTP i porównanie liczników bazy. Nie zmieniono danych ani poświadczeń w tym etapie.
