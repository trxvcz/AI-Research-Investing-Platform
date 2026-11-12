# Discovery i priorytetowe zadania

## Kronos — opcjonalne scenariusze cenowe (2026-11-02)

Status: wszystkie zadania KR poniżej są planowane. [Architektura i kontrakty do zaprojektowania](../architecture/kronos-scenarios.md). Ten tor nie zastępuje pierwszego raportu fundamentalnego. Zależności P2 odnoszą się do identyfikatorów w tym pliku (numeracja faz master planu jest odrębna). Nakład orientacyjny jednej osoby, bez oczekiwania na dane/przeglądy i obserwacji prospektywnej; bez deklarowanej ceny hostingu.

| Zadanie / właściciel roli | Zależności | Kryteria odbioru | Nakład |
|---|---|---|---|
| KR-00 dane i dopuszczenie / Architect + Quant | P0-03, P4-00, P2-03; do tego czasu tylko jawnie syntetyczne fixture | Wybrane darmowe źródło i rynek, prawa użycia/wyświetlania, polityka danych, PIT/korekty/sesje; audyt licencji i zakresu pretrainingu kodu/wag/tokenizera | 1–2 dni |
| KR-01 kontrakty / Architect | KR-00; projekt na fixture może poprzedzać aktywację źródła | PriceBarDataset/ForecastRequest/ForecastArtifact, limity i statusy, cache identity, jedna definicja Pydantic/Schema/OpenAPI; prognozy oddzielone od obserwacji; plan kompatybilności raportu | 1–2 dni |
| KR-02 lokalny benchmark / AI Integration | KR-01; rzeczywiste dane dopiero po KR-00 | Najpierw fixture i deterministyczne walidatory; przypięte mini/small, cold/warm p50/p95, RAM/VRAM, przepustowość, koszt zasobów i limity. Brak zerowania braków/niejawnego amount; pojedyncze ścieżki zachowane | 1–2 dni |
| KR-03 kwalifikacja / Quant | KR-02 i zweryfikowane dane KR-00 | Przed testem zamrożone progi jakości/zasobów, baseline ostatniej ceny, MAE/MASE i pokrycie/szerokość pasm, walk-forward i nietknięty OOS; kontrola pretraining leakage lub jawny brak dowodu i obserwacja prospektywna. Brak poprawy = feature wyłączony | 2–4 dni + okres obserwacji |
| KR-04 asynchroniczny worker / Backend + AI Integration | KR-03 PASS | Osobny pipeline, idempotencja/cache, heartbeat podczas inferencji, fencing publikacji, limity/retry/kill switch, walidacja OHLC, immutable artefakty; testy crash/lease takeover i brak duplikatów. Bez nowej kolejki bez potrzeby | 2–4 dni |
| KR-05 UI i raport / Frontend | KR-04, P1-03, nowy kontrakt wykresu/raportu | Horyzonty 5/20 sesji, historia oddzielona od prognozy, baseline, as_of/model/ograniczenia, queued/blocked/unavailable; dostępność i brak obietnic kalibracji. Stare raporty bez migracji/nadpisania | 2–3 dni |
| KR-06 hosting i odbiór / Backend + niezależny QA | KR-04; publikacja produktu po KR-05 | Pilot lokalny; wybór CPU/hybryda/GPU dopiero z benchmarku i budżetu. Przed zdalnym dostępem auth/TLS/prywatny DB, polityka danych, limity, backup/restore, monitoring i runbook/RPO/RTO/SLO; test worker offline. Bez zakupu w ramach planowania | 2–4 dni |

Delegować wyłącznie niezależne zakresy po uzgodnieniu kontraktów, maksymalnie 3 wykonawców, jeden właściciel pliku. Scheduler, fine-tuning i rozbudowa uniwersum są poza pilotem. Źródła techniczne oraz pułapki upstream zapisano w dokumencie architektury; nie ma wyników benchmarku ani aktywnego endpointu prognoz.

Data: 2026-10-30. Estymaty są orientacyjnym nakładem jednej osoby, bez oczekiwania na dostęp i przeglądy. Nie są terminami dostawy ani wyceną. M0–M6 to etapy startera; P0–P8 pochodzą z master planu i nie są równoważnymi numeracjami.

| Priorytet / zadanie | Stan i zależność | Kryteria odbioru | Nakład |
|---|---|---|---|
| P0-01 stan rzeczywisty | Wykonane lokalnie | Katalog/zapis/Git, przegląd kodu i audytu; npm test 4/4; 46/46 hashy przed dokumentacją | Wykonane |
| P0-02 discovery i ADR | Wykonane — A zaakceptowana 2026-10-30 | Zapisana opcja A i rola Node; bez kopiowania wcześniejszych zmian | Wykonane |
| P0-03 zakres i darmowe źródła | SEC dopuszczony dla pilota; pozostałe źródła wymagają osobnego przeglądu | Potwierdzone warunki i limity konkretnego źródła, prawa użycia, dowód braku płatnego fallbacku w projekcie adaptera | 0.5–1 dzień |
| P1-00 kontrakty v1 | Wykonane P1-00a i P1-00b w zakresie wejścia, odpowiedzi walidacji i koperty raportu/legacy | Jedna definicja; date-time, jednostki/okresy, synthetic/live oddzielone od kompletności; missing ≠ 0; rewizje, evidence, checksum i błędne wejścia; legacy pozostaje M0, bez dorabiania provenance. Nie obejmuje pełnego silnika raportów P5 | Wykonane |
| P1-01 środowisko i FastAPI | Wykonane dla lokalnego API walidacji po P1-00a | Python 3.12, lock zależności, health/ready/validate, pytest/lint/typecheck PASS; npm test PASS; CI skonfigurowane, zdalnie jeszcze nieuruchomione | Wykonane |
| P1-02 minimalna trwałość | Raporty, minimalny registry, manualny ledger i raw snapshots wykonane | Migracja0003, exact-byte archiwum, frozen inputs, CAS/retry, fail/resume i final report provenance;416 Python+4 Node PASS zrestore całego zestawu. Temporalne listingi pozostają dalszym zakresem | Worker: P1-02c poniżej |
| P2-01 adapter fundamentów | Pilot SEC wykonany (2 metryki rocznego10-K USD); rozszerzenia pozostają planowane | Raw/hash, jednostki/okresy/kontekst/revisions, limit retry, brak cofania first_seen; nieznane available_at blokuje historyczne użycie | 2–4 dni |
| P2-02 jeden rzeczywisty raport | Wykonany: Apple2025, PostgreSQL i JSON/HTML partial; [odbiór](../SEC_VERIFICATION.md) | Liczby porównane z dokumentem źródłowym, JSON/HTML partial bez cen/LLM; braki jawne, pełny lineage | 1–2 dni |
| P2-03 ceny EOD i corporate actions | Po P0-03 dla cen i P2-02 | Darmowy dostęp potwierdzony; limity, stale/missing, split/dividend, PIT; blokada quota bez dopłaty | 2–4 dni |
| P1-03 React PWA i klient API | Po stabilizacji kontraktów/API | TypeScript/Vite, klient z OpenAPI, statusy partial/blocked, klawiatura i responsywność; testy UI i migracja bez utraty starych raportów | 2–4 dni |
| P4-00 egzekwowanie free-only | Wykonane; pilot SEC dopuszczony po osobnym przeglądzie | Dokładne opłaty Decimal, aktualne warunki/polityka danych, trwałe wspólne quota PostgreSQL, blokada retry/refund/paid fallback; 605 Python +9 Node PASS. [Kontrakt](../FREE_ONLY_PROVIDERS.md) | Wykonane lokalnie i na bazie Docker |

P1-02c — wykonano lokalny worker deterministyczny z kolejką PostgreSQL, leases/fencing, odzyskiwaniem i migracją0004. Odbiór: 507 Python+4 Node PASS (2026-11-02), backup/restore/reclaim, niezależny QA. [Szczegóły](../WORKER_VERIFICATION.md). Docker działa: baza deweloperska ma head0007 po backupie. Scheduler, usługa systemowa, darmowy adapter i auth pozostają osobnymi zadaniami.

Kolejne zakresy master planu: pełne fundamenty/technika, AI z polityką danych, PDF, Strategy Lab, kolejka i produkcja. Oszacować po pierwszym przyroście. Bramka przeglądu ADR została spełniona; następne są raport/legacy i trwałość, a aktywacja źródła nadal wymaga weryfikacji darmowego dostępu. Nie wymaga zakupu ani płatnych fallbacków.

## Walidacja i bezpieczeństwo

Discovery: 4/4 istniejących testów PASS, także w niezależnym QA i ponownie po zmianach dokumentacji. Cztery schematy przechodzą parsowanie JSON i kontrolę deklaracji draftu; pełnego walidatora runtime nadal brak. QA tylko do odczytu potwierdził deterministycznie akceptację brakujących currency/unit/source_id oraz dodatniego kosztu przez router przy dodatnim budżecie. Nie aktywował źródeł ani nie zmieniał plików. Przegląd bezpieczeństwa opisano w current-state.md. JSON parsing lub przegląd schematów nie jest pełną walidacją JSON Schema. Przed merge kodu wymagane npm test, walidacja schematów i przegląd bezpieczeństwa; dla nowego stosu także kontrole z sekcji 9 master planu.

W tej sesji nie wykonano połączeń z dostawcami ani płatnych API; koszt infrastruktury i pracy nie był mierzony. Nie przypisywać mu fikcyjnej kwoty. MANIFEST.sha256.json zachowujemy jako opis startera, a nie dowód integralności nowych dokumentów.
