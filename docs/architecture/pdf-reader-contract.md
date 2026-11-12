# Czytnik PDF — P4-01c2c

Zakres: lokalne czytanie tekstowej warstwy PDF niezależnie od emitenta. Bez OCR, LLM, sieci, automatycznego pobierania i publikacji faktów. Istniejący DocumentPacket już dopuszcza format pdf. Kontrakty archiwum Create/Summary rozszerzamy o pdf i regenerujemy JSON Schema/OpenAPI/typy panelu; baza przechowuje format wewnątrz JSON i nie wymaga migracji. Stare formaty zachowują dotychczasowy odczyt.

Interfejs wewnętrzny: pdf_reader.read_pdf_blocks(raw: bytes) -> list[tuple[str, str]], zwracający locator i tekst. Błędy jako PDFReadError z zamkniętej listy kodów DOCUMENT_PDF_INVALID, DOCUMENT_PDF_ENCRYPTED, DOCUMENT_PDF_UNSAFE, DOCUMENT_PDF_LIMIT, DOCUMENT_PDF_TEXT_REQUIRED, DOCUMENT_PDF_UNAVAILABLE. document_readers mapuje je na DocumentReadError. Nie ujawniać treści, ścieżek ani wyjątków biblioteki.

Limit oryginału pozostaje 1MiB; najwyżej100stron,512bloków,32768znaków/blok i2MiB tekstu. Lokalizator pdf:page:N:block:M, numeracja od1; nie przestawiać tekstu według domniemanej semantyki tabel. Brak gwarancji układu kolumn, widoczności tekstu i zgodności warstwy OCR z obrazem. Wydobyty tekst pozostaje niezaufany i wymaga przeglądu. Brak tekstu na którejkolwiek stronie odrzuca cały dokument zamiast ukrywać niepełne czytanie.

Parser pypdf==7.0.1 w osobnym procesie, bez odziedziczonych sekretów środowiska, z limitem czasu i pamięci na Windows i Linux. Brak skutecznej konfiguracji limitu pamięci blokuje czytanie. Zasoby ustawić przed parsowaniem; odrzucać aktywne akcje, JavaScript, pliki osadzone, formularze, szyfrowanie i nieobsługiwane filtry. Proces ma ograniczone wejście/wyjście i nie wypisuje diagnostyki źródła. Nie wykonywać dokumentu ani odwołań zewnętrznych. Izolacja procesowa nie jest pełnym sandboxem systemu.

Odbiór: syntetyczne wielostronicowe PDF, deterministyczne bloki/hash, cyfry i cytaty zachowane, jawne odrzucenia malformed/encrypted/image-only/active/limits, sprzątanie procesu po timeout, archiwizacja PDF i odczyt bajtów, rewalidacja offline, panel z wyborem PDF. Nie pobierać rzeczywistych raportów ani nie uruchamiać modeli w tym etapie. Zachować istniejące pliki, dane i odłożone wdrożenie Oracle.
