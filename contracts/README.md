# Kontrakty

Nowe kontrakty wejścia i odpowiedzi walidacji Python są w `v1/`, generowane z Pydantic; instrukcje i semantyka: [DOMAIN_CONTRACTS_V1](../docs/DOMAIN_CONTRACTS_V1.md). Stare schematy w tym katalogu pozostają kontraktami demonstratora M0; ich runtime nie został zmieniony. Poniższy opis dotyczy M0.

JSON Schema 2020-12. Format date-time wymaga włączonego format validation. M1 dodaje walidator produkcyjny oraz ścisłe podschematy domenowe; pola fundamental/technical/metrics są celowo otwartymi szkicami. Testy startera sprawdzają strukturę dema, nie zastępują pełnego JSON Schema.
