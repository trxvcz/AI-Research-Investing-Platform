# Kontrakt prywatnego wdrożenia — etap P6-01c

Status: zakres implementacji i odbioru lokalnego, bez zgody na publiczne wystawienie lub zakup VPS. Lokalny panel developerski pozostaje na 127.0.0.1:8082. Osobny wariant kontenerowy ma jedno konto właściciela, HTTPS, prywatną sieć backendu i bazy oraz restart procesów przez Docker.

## Granica HTTP

Nowa fabryka `alphasense.private_server:create_app` chroni wszystkie ścieżki przed odczytem i zapisem przez HTTP Basic. Nie ma wyjątku dla archiwum, raportów, plików, OpenAPI lub statusów. Sekret to wygenerowany losowy token 256-bitowy używany jako hasło; nie przyjmujemy wybranego przez użytkownika słabego hasła. Backend przechowuje tylko jego SHA-256 i porównuje stałoczasowo. Nagłówki autoryzacji i treść błędów konfiguracji nie trafiają do logów ani odpowiedzi.

`ALPHASENSE_PRIVATE_AUTH_FILE` wskazuje ograniczony plik JSON z dokładnymi polami `username` (domyślnie owner) i `token_sha256` (64 małe znaki hex). `ALPHASENSE_PRIVATE_ORIGIN` jest obowiązkowym kanonicznym origin HTTPS, bez ścieżki, query i fragmentu. Brak lub błędna konfiguracja blokuje start; nie uruchamia trybu bez ochrony.

TLS kończy Caddy. Backend nie ufa klientowskim X-Forwarded-*; uruchamiamy uvicorn z `--no-proxy-headers`. Prywatny middleware sprawdza Host względem skonfigurowanego origin i ustawia w kopii scope schemat HTTPS oraz `alphasense.panel_origin`. `verify_panel_request` akceptuje ten origin wyłącznie z zaufanego scope middleware; bez niego zachowuje dotychczasową granicę localhost. Wszystkie zapisy nadal wymagają Origin, JSON, nagłówka panelu i dozwolonej ścieżki. Prywatny host zachowuje whitelistę zapisów lokalnego panelu. Żaden nowy endpoint sterowania bazą lub workerami nie powstaje.

Domyślny proxy słucha wyłącznie 127.0.0.1:8443 i ma origin https://localhost:8443 oraz `tls internal`. Dostęp na VPS odbywa się przez tunel SSH na ten sam port. CA pozostaje własnością tego wdrożenia; test klienta weryfikuje certyfikat z jawnym plikiem CA, bez wyłączania walidacji i bez instalowania zaufania w systemie użytkownika. Publiczna domena/porty i publicznie zaufany certyfikat wymagają oddzielnej konfiguracji.

## Sekrety i procesy

Generator zapisuje wyłącznie nowe pliki w nowym katalogu: access.json, owner-token.txt, postgres-password.txt, database-url.txt i pusty sec-user-agent.txt. Nie drukuje ich zawartości i nie nadpisuje istniejącego katalogu lub .env. Token właściciela nie jest montowany do kontenerów; API dostaje tylko hash. Plik URL bazy i hasło PostgreSQL są sekretami Compose, nie build args lub zwykłym środowiskiem Compose.

Na POSIX katalog ma 0700 i pozostaje własnością operatora, owner-token.txt ma 0600. Pliki montowane indywidualnie jako read-only secrets mają 0444: ich nadrzędny katalog blokuje dostęp innych użytkowników hosta, a procesy kontenerów o różnych UID mogą odczytać swoje konkretne mounty. Nie należy kopiować tych plików do katalogu dostępnego innym użytkownikom ani zmieniać 0700 rodzica. Ustawienia Compose uid/gid/mode nie zastępują uprawnień bind-mount plików. Na Windows obowiązują odziedziczone ACL; generator nie poświadcza ich poufności.

Nowe wejście `alphasense.private_runtime` ładuje ograniczone pliki ALPHASENSE_DATABASE_URL_FILE oraz opcjonalny ALPHASENSE_SEC_USER_AGENT_FILE do środowiska procesu, a następnie uruchamia jawnie wybraną rolę: api, sec-worker, document-worker, scheduler lub migrate. Nie ładuje kluczy modeli i nie zmienia provider-policy. Migracja jest osobną, jawną operacją; procesy nie wykonują jej przy starcie.

Osobny Dockerfile i compose.private.yaml pozostawiają demonstrator Node i istniejący PostgreSQL bez zmian. Nazwane wolumeny oraz projekt Compose są odrębne. Obraz kopiuje jawnie tylko kod i niezbędne kontrakty/konfiguracje; ignoruje sekrety, .git i .local-postgres. Aplikacja pracuje jako użytkownik bez roota, ma read-only filesystem i osobny wolumen katalogu SEC. Hasła nie trafiają do obrazu. Caddy i PostgreSQL używają własnych wolumenów. Backend i PostgreSQL nie publikują portów.

Obraz wymaga prawdziwego BUILD_GIT_SHA przekazanego z repo. Worker może użyć go bez instalacji git; hash rzeczywistych plików implementacji nadal rozróżnia niezacommitowane zmiany. Sam SHA nie poświadcza czystego drzewa źródeł.

Docker restartuje zakończone procesy według unless-stopped. Sam wynik healthcheck nie restartuje kontenera; nie deklarujemy HA. Przypadek nagłego przerwania nadal opisuje istniejący rejestr sesji i lease kolejki. Domyślna konfiguracja nie zawiera aktywnych harmonogramów ani kluczy modeli.

## Odbiór

Testy objęły ochronę odczytów i zapisów, brak wpływu fałszywych nagłówków proxy, CSRF/Origin, błędy konfiguracji i redakcję sekretów, zgodność lokalnego panelu, konfigurację Compose i build. Próba kontenerowa była odrębna od lokalnych danych użytkownika, z danymi syntetycznymi i własnymi sekretami. Potwierdzono TLS z walidacją CA, dostęp do raportu po logowaniu i restart workera; dodano init do przekazywania sygnałów. [Odbiór i instrukcja](../PRIVATE_DEPLOYMENT.md). Nie oznaczamy tego jako wdrożenia na VPS.
