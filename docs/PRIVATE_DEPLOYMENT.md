# Prywatne wdrożenie — P6-01c1a

Pakiet FastAPI/PostgreSQL/React jest przygotowany i sprawdzony lokalnie w osobnym projekcie Compose. Nie jest to wdrożenie na VPS. Demonstrator Node i lokalny panel 8082 pozostają osobnymi procesami. Research-only; brak zleceń i nowych wywołań modeli.

Docelowy dostawca VPS: Oracle Cloud, zgodnie z ostateczną decyzją właściciela po rozważeniu AWS. Instancja, region, architektura CPU i dostęp SSH nie zostały jeszcze wskazane ani skonfigurowane. Ten zapis nie oznacza uruchomienia zasobów lub zgody na koszty infrastruktury. Procedura poniżej dotyczy prywatnego wdrożenia na wybranej instancji Linux.

Na pierwszy pilot wybieramy Ubuntu 24.04 LTS i proponujemy Ampere A1 (ARM), 2 OCPU, 12 GB RAM oraz dysk 50 GB, pod warunkiem dostępności i potwierdzenia bezpłatnego przydziału w koncie. Przed utworzeniem sprawdź sumę istniejących zasobów i [aktualne warunki Always Free](https://docs.oracle.com/en-us/iaas/Content/FreeTier/freetier_topic-Always_Free_Resources.htm). Obraz aplikacji wymaga rzeczywistego odbioru na ARM. Dopuść TCP22 tylko z własnego publicznego IP; nie otwieraj portów bazy i panelu. PostgreSQL pozostaje w istniejącym Compose. Faktyczny odbiór wymaga sprawdzenia restartu hosta i odtworzenia kopii na Oracle Cloud.

## Pierwsze uruchomienie na Linuxie

Wymagania: Docker Engine z Compose, Python 3, Git, dostęp SSH i wolny port loopback8443. Uruchamiaj z katalogu tego repo. Używaj stałej nazwy projektu; inna nazwa tworzy inne wolumeny.

```sh
export ALPHASENSE_BUILD_GIT_SHA="$(git rev-parse HEAD)"
export ALPHASENSE_PRIVATE_IMAGE_TAG=private-v1
export ALPHASENSE_PRIVATE_SECRETS_DIR="$PWD/.local-postgres/private-deploy"
mkdir -p .local-postgres
python3 scripts/create_private_secrets.py --directory "$ALPHASENSE_PRIVATE_SECRETS_DIR"
docker compose -p alphasense-private -f compose.private.yaml build api
docker compose -p alphasense-private -f compose.private.yaml up -d db
docker compose -p alphasense-private -f compose.private.yaml --profile ops run --rm migrate
docker compose -p alphasense-private -f compose.private.yaml up -d api sec-worker document-worker scheduler proxy
docker compose -p alphasense-private -f compose.private.yaml ps
```

Generator odmawia nadpisania katalogu. Na POSIX katalog ma0700, token właściciela0600, pliki montowane indywidualnie0444, by różne UID kontenerów mogły je czytać. Nie udostępniaj katalogu innym użytkownikom. Na Windows sprawdź ACL katalogu; generator nie ustawia prywatnych ACL. Sekrety nie trafiają do obrazu ani konfiguracji środowiska Compose. Docker i administrator hosta nadal mają dostęp do sekretów. [Mechanizm Compose secrets](https://docs.docker.com/compose/how-tos/use-secrets/).

Hasło logowania to zawartość owner-token.txt, użytkownik owner. Nie wklejaj tokenu do czatu, URL ani poleceń zapisywanych w historii. API otrzymuje tylko hash losowego tokenu. Wszystkie ścieżki HTTP wymagają logowania, także health/ready/OpenAPI/archiwum. API healthcheck potwierdza401, czyli działanie ochrony; gotowość bazy potwierdza dopiero uwierzytelnione /ready.

sec-user-agent.txt jest początkowo pusty. Przed świadomym użyciem SEC wpisz uzgodnioną identyfikację kontaktową i odtwórz api oraz sec-worker. Nie przenoś całego pliku.env ani kluczy modeli. Aktualne ograniczenia źródeł i quota nadal obowiązują. Harmonogramy są domyślnie wstrzymane; dokumenty mają wykonawcę offline, bez aktywnego LLM.

## Dostęp z własnego komputera

```sh
ssh -N -L 8443:127.0.0.1:8443 USER@VPS
```

Otwieraj https://localhost:8443/panel/. Port8443 VPS jest związany wyłącznie z127.0.0.1; API i baza nie publikują portów. Nie zmieniaj bind na0.0.0.0. SSH/firewall i automatyczny start usługi Docker konfiguruje operator VPS.

Caddy używa prywatnego CA ([tls internal](https://caddyserver.com/docs/caddyfile/directives/tls)). Skopiuj tylko publiczny certyfikat:

```sh
docker compose -p alphasense-private -f compose.private.yaml cp proxy:/data/caddy/pki/authorities/local/root.crt .local-postgres/private-root.crt
```

Przenieś publiczny certyfikat przez uwierzytelnione SSH. Przed ręcznym dodaniem do zaufanych CA porównaj fingerprint po obu stronach. Próba lokalna używała jawnego cafile, bez instalowania CA i bez wyłączania walidacji. Nie pomijaj ostrzeżenia certyfikatu. Nie kopiuj klucza prywatnego CA. Publiczna domena/TLS to oddzielna konfiguracja.

## Restart, kopia i odtworzenie

Kontenery mają unless-stopped; zakończenie procesu uruchamia go ponownie. Proces init aplikacji przekazuje sygnały i zbiera zakończone procesy potomne. W próbie worker dokumentów po SIGTERM wystartował ponownie, RestartCount wzrósł do1. Healthcheck sam nie restartuje zawieszonego procesu. To nie jest HA. [Polityka restart](https://docs.docker.com/reference/compose-file/services/#restart). Rejestr w panelu pokazuje heartbeat i utratę kontaktu. Po aktualizacji sprawdź /ready i trzy rodzaje wykonawców.

Backup wykonuj do prywatnego katalogu, z szyfrowaną kopią poza serwerem. Poniższe przekierowania binarne są dla powłoki Linux, nie Windows PowerShell5:

```sh
umask 077
docker compose -p alphasense-private -f compose.private.yaml exec -T db pg_dump -U alphasense -d alphasense -Fc > research.dump
```

Osobno zachowaj katalog sekretów i wolumeny sec_catalog oraz caddy_private_data (CA), z kontrolą dostępu. Snapshot wolumenu PostgreSQL wymaga zatrzymania bazy lub narzędzia świadomego PostgreSQL; nie kopiuj działającego PGDATA zwykłym cp. Nie używaj down --volumes do aktualizacji.

Odtwarzanie najpierw sprawdź w NOWYM projekcie i pustej bazie: wygeneruj oddzielne sekrety, uruchom tylko db, następnie pg_restore. Nie uruchamiaj schedulerów przed oceną zapisanych terminów i świadomym wznowieniem pracy.

```sh
docker compose -p alphasense-restore -f compose.private.yaml exec -T db pg_restore -U alphasense -d alphasense --exit-on-error --no-owner --no-privileges < research.dump
```

Dla projektu restore ustaw własny ALPHASENSE_PRIVATE_SECRETS_DIR. Zweryfikuj migrację, raporty, hashe archiwum, historię i harmonogramy przed użyciem tej bazy. Nie odtwarzaj powyższym poleceniem do istniejących danych.

Token właściciela rotuj przez nowy losowy token i odpowiadający hash w access.json, zachowując uprawnienia; odtwórz API i sprawdź, że stary token otrzymuje401. Zmiana postgres-password.txt sama nie zmienia hasła istniejącej bazy — wymaga skoordynowanej zmiany roli PostgreSQL i database-url.txt.

Obraz zawiera również narzędzia z requirements-dev.lock; dalsze odchudzenie obrazu i przypięcie baz do zatwierdzonych digestów pozostają zadaniem utrzymania. BUILD_GIT_SHA identyfikuje commit bazowy, a nie poświadcza czystego drzewa; worker dodatkowo zapisuje hash implementacji.

## Odbiór lokalny 2026-11-10

Osobny obraz i wolumen PostgreSQL, migracja do0014, weryfikowane TLS,401 bez hasła,200 dla uwierzytelnionych panel/ready, trzy aktywne rodzaje wykonawców, odrzucenie obcego Origin i zapis wstrzymanego harmonogramu. Generator sprawdzony również na Linuxie z umask077. Regresja1248 Python PASS, panel53/53 i Node9/9; poprawka healthchecku dodatkowo sprawdzona po rozwiązaniu konfiguracji Compose. Brak nowych pobrań SEC i wywołań modeli. Końcowy przegląd wykonał koordynator po wyczerpaniu limitu podagentów.

Rzeczywisty VPS, autostart po restarcie hosta i odtworzenie prywatnego wdrożenia na docelowym serwerze pozostają nieodebrane. Lokalne testy odtwarzania archiwum/kolejek/schedulera są częścią regresji, nie dowodem odzyskania docelowego VPS.
