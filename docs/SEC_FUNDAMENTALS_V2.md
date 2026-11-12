# Rozszerzone fundamenty SEC — v2

Kontrakt przyrostu2026-11-06. Osobny pipeline `sec-fundamentals-v2`; stare przebiegi v1 zachowują swój zestaw trzech źródeł. Nowa wersja wymaga ośmiu potwierdzonych snapshotów, wszystkich pobranych przez tę samą bramkę free-only i wspólną quota.

| Metryka | Jawny tag US-GAAP | Kontekst |
|---|---|---|
| Gotówka i ekwiwalenty | CashAndCashEquivalentsAtCarryingValue | stan na dzień końca roku |
| Dług długoterminowy, część bieżąca | LongTermDebtCurrent | stan na ten sam dzień |
| Dług długoterminowy, część niebieżąca | LongTermDebtNoncurrent | stan na ten sam dzień |
| Przepływy operacyjne | NetCashProvidedByUsedInOperatingActivities | ten sam roczny okres co wynik |
| Nakłady na rzeczowe aktywa trwałe | PaymentsToAcquirePropertyPlantAndEquipment | ten sam roczny okres |

Pozostają przychód i wynik netto. Marża netto to wynik/przychód. Wolne przepływy są tu ograniczonym obliczeniem OCF−capex, wymagającym dostępnych wartości, tego samego okresu i waluty. Nie stanowią wyceny. Dwie części długu nie oznaczają całkowitego zadłużenia i nie obejmują automatycznie wszystkich kredytów/leasingu/innych zobowiązań. Gotówka nie obejmuje wszystkich papierów wartościowych.

Instant ma period_start=period_end=report_date. Roczne przepływy nie są traktowane jak stany bilansowe. Źródła wymagają zgodnego CIK, accession, filed/form, USD, hashy i lokalnego first_seen. Porównania historyczne i wzrost rok do roku pozostają dalszym zakresem.

Każdy endpoint musi dostarczyć prawidłowy JSON. HTTP404 lub inny błąd transportu blokuje import; nie tworzymy fikcyjnego payloadu ani zera. Jeśli prawidłowa odpowiedź nie zawiera pasującego faktu, metryka pozostaje missing. Nie ma automatycznej zmiany tagu/fallbacku. Ograniczenie oznacza, że część emitentów z katalogu nie przejdzie tego pilota. Dowody brakujących endpointów404 wymagają osobnego kontraktu archiwizacji przed ich obsługą jako missing.

Migracja0008 rozszerza dozwolone zasoby receipts i reguły pipeline. Wykonanie na właściwej bazie następuje po backupie. Backup przed migracją `.local-postgres/backups/before-v2-20261106.dump`,227583b, SHA2568487baef29c4333042a6814a454b0e68c17728b6ca268b12800afb179cb96996.

## Odbiór runtime2026-11-06

Po backupie zastosowano0008 na właściwej bazie. PilotApple run_id e1298871-72e6-45e8-9b9e-349296865920 nie utworzył przebiegu ani raportu: pierwsza próba bez User-Agent zakończyła się kontrolowaną odmową; po wczytaniu konfiguracji importer zapisał cash/debt_current/debt_noncurrent i zatrzymał się na QUOTA_EXHAUSTED. W bieżącym oknie użyto20/20. OCF/capex pozostają do pobrania, bez zwiększania limitu i bez fikcyjnych danych. Ponowienie tego samego UUID w kolejnym świadomie otwartym oknie użyje sześciu istniejących receipts. Nie deklarujemy rzeczywistego raportu v2.

Parser/worker100 przypadków PASS, backendpanel13 oraz migracja/import22 PASS. Frontend8/8 i buildPASS. QA wykrył niebezpieczne poszerzenie mapy źródeł v1; naprawiono przez jawne trzy role i6regresji. Kontrole Ruff/mypy/schematów/OpenAPI PASS.

Końcowa regresja2026-11-06:826 Python PASS (243.87s), Node9/9 PASS, panel8/8+buildPASS, Ruff/mypy/schematy/OpenAPI PASS. `/ready`200 oraz odczyt wcześniejszego raportuGOOGL200 po migracji. Pilotv2 pozostaje niedokończony z powodu quota20/20; brak deklaracji rzeczywistego raportuv2.

## Ukończony odbiór2026-11-09

Dopuszczenie SEC pozostawało ważne do2026-11-09T16:09:26.230905Z. Świadomie otwarto niepokrywające się okno2026-11-09T00:00:00Z–2026-11-10T00:00:00Z, nadal20prób, bez resetowania starych liczników i bez automatycznego przedłużenia przeglądu. Pobrano brakujące OCF i capex; sześć wcześniejszych receipts wykorzystano z archiwum.

Przebieg e1298871-72e6-45e8-9b9e-349296865920 zakończonycompleted. Report20b20784-d987-544f-8c39-2539cfec0bf1 revision1, revision_id fcc8ce7d-054d-5880-9d91-5d3a0cc6946d. Raportpartial zawiera7 dostępnych obserwacji: revenue416161mlnUSD, netincome112010mln, cash35934mln, currentlongtermdebt12350mln, noncurrentlongtermdebt78328mln, OCF111482mln, capex12715mln. OCF−capex=98767mlnUSD. Instant2025-09-27, przepływy2024-09-29–2025-09-27. Nie określamy sumy części długu jako totaldebt.

NiezależnyQA potwierdził metadane7 źródeł, hashe, referencjeFCF i kwoty w [Apple10-K2025](https://www.sec.gov/Archives/edgar/data/320193/000032019325000079/aapl-20250927.htm). JSON/HTML zapisano w artifacts/sec-research/fcc8ce7d-054d-5880-9d91-5d3a0cc6946d. Backup po pilocie `.local-postgres/backups/after-v2-pilot-20261109.dump`,273153b, SHA2565250223c9f22eafec5d01ca52db2aafb13139fc967f1937403d79398bdf2b793.

Retest parsera/eksportu12/12PASS, Node9/9PASS; wcześniejsza pełna regresja826PASS pozostaje historycznym wynikiem. Brak zmian algorytmów w tym odbiorze.
