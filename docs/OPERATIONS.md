# 24/7, powiadomienia i bezpieczeństwo

## Plan hostowania Kronosa — 2026-11-02

Kronos nie jest wdrożony ani dodany do Compose. Obowiązuje [plan scenariuszy i hostingu](architecture/kronos-scenarios.md): lokalny pilot i pomiar CPU/ewentualnego dostępnego GPU, następnie wybór infrastruktury z budżetem, bez automatycznego zakupu. API i worker modelu to oddzielne procesy; wyłączony worker pozostawia zadania queued/unavailable, a zapisane raporty można czytać.

Planowany hosting zdalny wymaga auth/TLS, prywatnej bazy i chronionego połączenia workera, przypiętych wag/obrazów, limitów zasobów/kolejki, heartbeat podczas inferencji i fenced publication, monitorowania oraz testu backup/restore artefaktów wraz z bazą. Obecny worker nie udostępnia zdalnego API claim; wariant hybrydowy wymaga osobnej implementacji lub prywatnego tunelu. Nie wystawiać PostgreSQL ani serwera modelu publicznie. Obsługa produkcyjna: [KR-06](roadmap/issues.md#kronos--opcjonalne-scenariusze-cenowe-2026-11-02); scheduler pozostaje poza pilotem.

## Ogólne wymagania operacyjne
Demo: pojedynczy proces, restart unless-stopped i healthcheck; nie zapewnia HA ani automatycznego restartu po unhealthy. Docelowo osobne API/workers/scheduler, trwałe lease/heartbeat, retry exponential jitter, idempotencja, DLQ i outbox. Harmonogram wg sesji i publikacji, UTC wewnątrz; deduplikuj alerty i respektuj quiet hours Europe/Warsaw. Telegram/web push wymagają zgody i konfiguracji; nie zapisuj tokenów w logach.
Monitoring: backlog/age, data freshness, failed jobs, provider latency/429, token/cost spend, budget blocked, report errors, backup age, notification delivery. Dashboard i alerty dla operatora; readiness sprawdza wymagane zależności, liveness tylko proces. Ustal SLO i runbook awarii; kill switch blokuje nowe LLM joby.
Produkcja: TLS reverse proxy, OIDC/RBAC i tenant isolation, CSP, CSRF dla sesji, rate limits, rozmiary uploadów, allowlist egress/SSRF, secret manager, rotacja, audit trail z redakcją PII. Nie wykonuj promptów z dokumentów. Modele bez dostępu do sekretów i kodu wykonawczego. Dane dostawców zgodnie z licencją i retencją.
Backup PostgreSQL i obiektów szyfrowany; test restore oraz RPO/RTO ustalone przez operatora. Przypnij obrazy po digest przed wdrożeniem, aktualizuj zależności i skanuj obrazy. Compose to środowisko lokalne, nie gotowa infrastruktura produkcyjna.
