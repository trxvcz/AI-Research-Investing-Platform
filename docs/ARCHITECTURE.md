# Architektura
PWA → API → trwała kolejka → Orchestrator → Data → Fundamental → Technical → Strategy Lab (opcjonalny) → Report → Independent Reviewer → Publish + outbox notification.
Fundamental musi zakończyć się przed technical; brak dowodów daje status blocked/partial. Reviewer może odrzucić publikację; zachowuj także nieudane runy i powód. Demo wykonuje role sekwencyjnie; zadania różnych instrumentów mogą działać równolegle z limitem.
Docelowo PostgreSQL: runs/jobs/budget_ledger/outbox; object storage: niezmienne raw snapshots, Parquet, raporty; Redis opcjonalnie cache/queue. Nie traktuj Redis jako jedynego trwałego rejestru. Idempotency key = asset + as_of + input hash + config/code version. Każda wersja raportu ma nowy ID i parent_id, hash danych, kodu i promptów oraz trace kosztów.
API demo jest lokalne i tylko do odczytu; /health, /ready, /reports, /reports/{id}/report.html. Analityka przez npm run demo. Nie wystawiaj API w Internecie przed M6.
Provider Protocol: capabilities, estimate, invoke, normalize, health. Adaptery danych rozdziel raw i normalized z jednostką/walutą/available_at/licencją. Modele nie otrzymują narzędzi transakcyjnych.
