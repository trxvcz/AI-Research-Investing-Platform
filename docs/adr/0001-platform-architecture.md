# ADR-0001 — Python/React jako cel, Node jako demonstrator

Data: 2026-10-30. Status: ACCEPTED — opcja A zatwierdzona przez właściciela odpowiedzią „dawaj” po przedstawieniu rekomendacji i dokumentów. Rozpoczynamy pierwszy przyrost fazy 1.

## Kontekst

Master plan wskazuje Python/FastAPI/Pydantic i React/TypeScript, a działający kod to samodzielny demonstrator Node M0. Rozwinięcia na C: nie są częścią tego repo. Nie wolno utożsamiać skopiowania ich z realizacją master planu.

Sekcja 10 ALPHASENSE_CODEX_MASTER_PLAN.md wymaga: „Do NOT implement Phase 1 until the discovery report and ADR are reviewed.” Dokumenty przedstawiono właścicielowi, który zatwierdził rekomendowany wariant A. Ta bramka została spełniona 2026-10-30.

## Opcje

| Opcja | Skutek | Koszt i ryzyko |
|---|---|---|
| A — Python/FastAPI + React jako cel; Node demonstratorem | Zgodność z master planem, jeden docelowy silnik | Port kontraktów i testów; potrzebne środowisko Python |
| B — Node jako docelowy backend | Wykorzystanie obecnego runtime | Wymaga jawnej zmiany master planu; nadal brak realnych danych i zabezpieczeń |
| C — dwa docelowe backendy analityczne | Równoległy rozwój | Duplikacja logiki, testów i kosztu utrzymania |

## Przyjęta decyzja

Wybrać A. Zachować Node i raporty; nie przenosić masowo 55 plików. Wykorzystać wyłącznie indywidualnie przejrzane wymagania, kontrakty i fixture. Docelowe moduły powstają w tym repo po przeglądzie ADR. React wdrażać w osobnym tickecie, bez przedstawiania obecnej PWA jako React. Opcji C nie rekomendujemy z uwagi na koszt utrzymania.

Niezależnie od opcji obowiązuje decyzja użytkownika: wyłącznie darmowe źródła, bez płatnych fallbacków i bez zleceń. Płatna rezerwa w zewnętrznym ADR-002 nie zostaje przyjęta. Ogólna polityka „najtańszy kwalifikowany provider” wymaga zawężenia do jawnie dopuszczonych darmowych opcji i blokady poza limitem; samo ustawienie budżetu zero nie zastępuje takiej kontroli. To wymaganie do implementacji, nie aktualna gwarancja runtime.

## Konsekwencje i bramka

- Discovery znajduje się w `docs/architecture/current-state.md` i `target-state.md`; zależności i odbiór w `docs/roadmap/issues.md`.
- Akceptację A zapisano 2026-10-30. Pierwszy przyrost obejmuje kontrakty wejścia i API walidacji FastAPI bez LLM/cen. Nie realizować równolegle wariantu B.
- Jeżeli właściciel wybierze B, najpierw jawnie zaktualizować master plan i ADR. Nie zmieniać planu niejawnie.
- Zachować historię i pliki użytkownika; żaden commit/push ani zakup nie wynika z tego dokumentu.
- Architektura nie gwarantuje dostępu do danych ani PIT. Aktywacja źródła wymaga aktualnej weryfikacji warunków i testu rzeczywistego źródła.
