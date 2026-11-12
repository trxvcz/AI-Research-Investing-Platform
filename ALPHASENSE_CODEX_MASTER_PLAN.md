# AlphaSense AI Research Platform — Master Plan for Codex

## Decyzja właściciela — 2026-11-11: synteza raportów Gemini Paid

Właściciel dopuścił Gemini Paid z limitem50PLN, interpretowanym jako łączny bez odnawiania, i potwierdził Paid/Tier1 obecnego klucza. Wyjątek dotyczy generowania polskiej interpretacji zapisanych danych SEC, nie płatnych źródeł, automatycznego fallbacku, zleceń lub dowolnych zewnętrznych wywołań. PostgreSQL egzekwuje rezerwację1PLN na próbę i idempotencję. [Wdrożony zakres i ograniczenia](docs/AI_ANALYSIS.md). GPW, predykcje i wdrożenie VPS pozostają planem.

## Aktualizacja planu — 2026-11-02: opcjonalny Kronos

Status: zaplanowano, nie wdrożono. Źródłem szczegółowej decyzji jest [architektura Kronosa i hostingu](docs/architecture/kronos-scenarios.md); kolejność i kryteria: [KR-00–KR-06](docs/roadmap/issues.md#kronos--opcjonalne-scenariusze-cenowe-2026-11-02). Obowiązuje research-only, darmowe źródła i brak płatnych fallbacków. Ta aktualizacja nie zezwala na zakup hostingu ani wywoływanie zewnętrznych modeli.

- Dodatkowy moduł „Scenariusze cenowe” obok deterministycznej techniki: jeden rynek equity/ETF, EOD, 5/20 sesji, mini/small wybrane po benchmarku, bez fine-tuningu. Nie jest strategią ani mechanizmem zleceń.
- Osobny worker poza API, kolejka PostgreSQL z leases/fencing, zamrożone dane i immutable ForecastArtifact/cache. Redis/Celery z dalszego tekstu to opcja warunkowa, nie obowiązkowa zależność. Nie rozszerzać obecnego pipeline deterministycznego niejawnie.
- Nowe wersjonowane kontrakty PriceBarDataset/ForecastRequest/ForecastArtifact do implementacji; prognozy odseparowane od historycznych obserwacji. Powiązanie modelu i wykresu z raportem wymaga jawnej ewolucji kontraktu v1; stare raporty pozostają czytelne.
- Kolejność: zweryfikowane darmowe świece i polityka danych → kontrakty/fixture → lokalny benchmark → walk-forward/OOS i kontrola pretraining leakage → worker/cache → UI/raport → zdalny hosting. Brakujące dane nie stają się zerami, a rozrzut próbek nie jest automatycznie skalibrowanym prawdopodobieństwem.
- Lokalny pilot bez zakupu serwera; CPU/hybryda/GPU dopiero na podstawie jakości, latencji, pamięci i pełnego kosztu. Zdalne wdrożenie wymaga auth/TLS, prywatnej bazy, backup/restore, monitoringu i polityki danych. Brak gwarancji 24/7/HA.

Encje i API w dalszym planie są docelowe, nie listą działających endpointów. Numery KR są osobnym torem, a historyczne identyfikatory P w tym master planie różnią się od szczegółowego backlogu. Pierwszy raport fundamentalny zachowuje priorytet.

## 0. Mission and boundaries
Build a research-only multi-asset investment analysis platform from scratch. No broker connections, order placement, execution, or personalized buy/sell directives. Support equities, ETFs, commodities, and later crypto. Each completed research run must produce an immutable versioned report with reproducible charts, source references, data-as-of timestamps, model provenance, and machine-readable results.

## 1. Engineering principles
- Monorepo, typed contracts, modular monolith first; split workers only when justified.
- Python 3.12+, FastAPI, Pydantic v2, SQLAlchemy/Alembic, PostgreSQL, Redis/Celery for async jobs; React/TypeScript/Vite PWA, TanStack Query, Plotly/ECharts; Parquet/DuckDB for historical data; S3-compatible object storage for artifacts.
- Docker Compose for local development; CI lint, type-check, tests, migrations, dependency/security scanning.
- Separate deterministic analytics from LLM narrative. No arbitrary LLM-generated Python execution.
- Idempotent jobs, audit trails, dataset snapshots, reproducible computation and cost quotas.
- Start with end-of-day US equities and ETFs; commodity fundamentals need asset-specific feeds and explicit missing-data states.

## 2. Modules
1. Identity & permissions: users, workspaces, roles, API keys stored encrypted server-side, audit.
2. Instrument registry: stable internal IDs, symbol exchange currency mappings, instrument type, corporate actions, delistings.
3. Data ingestion: provider adapters, price OHLCV, fundamentals, SEC filings, macro series, commodities supply/demand/inventories/futures; timestamps `event_time`, `published_at`, `ingested_at`; validation, licensing, freshness.
4. Fundamental engine: equities growth/margins/FCF/ROIC/leverage/valuation/peers, assumptions-based DCF and scenarios; ETFs holdings/fees/exposure/tracking; commodities balance, inventories, term structure, seasonality, macro/geopolitical risks; show `not_applicable` instead of inventing ratios.
5. Technical engine: trend, moving averages, RSI, MACD, ATR, volatility, volume, support/resistance with deterministic algorithms and explicit parameter sets; no future leakage.
6. Multi-model gateway: provider interface for OpenAI/Anthropic/Gemini/Ollama/OpenAI-compatible; capability discovery, schema-validated structured output, routing per task, fallback, timeout, retries, token/cost accounting, prompt/model versions, human review, prompt injection defense.
7. Research orchestrator: queued workflow `fetch -> validate -> fundamentals -> technicals -> synthesis -> charts -> report -> archive -> notify`; partial failures visible, retry-safe.
8. Strategy Lab: strategy DSL/schema, parameter bounds, scan, deterministic backtest, walk-forward, embargo/purging where needed, untouched OOS, transaction costs/slippage, corporate actions, benchmark, multiple testing correction, paper observation only.
9. Report engine: HTML-first canonical template, print-ready PDF export, optional JSON export; charts as versioned SVG/PNG and interactive views; citation provenance and methodology; immutable report revisions.
10. Monitoring: scheduling by market calendar, Telegram/email/in-app notifications, budgets, stop flag, queue health, stale data detection.

## 3. Domain entities
`Instrument`, `Provider`, `Dataset`, `DatasetSnapshot`, `CorporateAction`, `FundamentalObservation`, `MacroObservation`, `PriceBar`, `ResearchRun`, `ResearchStep`, `AnalysisResult`, `ChartArtifact`, `Report`, `ReportRevision`, `ModelProvider`, `ModelConfig`, `ModelInvocation`, `StrategyDefinition`, `BacktestRun`, `ValidationResult`, `PaperSignal`, `Alert`, `AuditEvent`.

Report fields: report_id, instrument_id, asset_type, generated_at_utc, data_cutoff_utc, snapshot_ids, source_links, methodology_version, pipeline_git_sha, model/provider/version, prompt_template_version, chart_artifact_ids, key_metrics, uncertainties, limitations, fundamental_section, technical_section, synthesis_section, scenario_section, disclaimer, checksum.

## 4. API v1
- `GET /instruments?query=` and `GET /instruments/{id}`
- `POST /research-runs` with instrument, scope, model policy, report format; returns job id
- `GET /research-runs/{id}` with status, steps, errors and artifact links
- `GET /instruments/{id}/reports`, `GET /reports/{id}`, `GET /reports/{id}/pdf`, `GET /reports/{id}/charts`
- `GET/POST /model-configs`, `POST /model-configs/test` (admin, secrets never returned)
- `POST /strategy-experiments`, `GET /backtests/{id}`, `GET /strategies`
- `GET/POST /schedules`, `GET /alerts`, `POST /admin/research-pause`
Use OpenAPI-generated TypeScript client and cursor pagination.

## 5. Report requirements and chart inventory
Every completed run persists a report even when analysis is inconclusive; missing sections explicitly disclose missing inputs. For equities: price vs benchmark, revenue/earnings/FCF history, margins, valuation multiples vs peers, leverage, scenario valuation sensitivity. For commodities: spot and futures term structure (when licensed), inventory series, production/consumption, seasonality, correlation to macro drivers. Technical: candlestick + MA + volume, RSI/MACD, volatility and drawdown. Strategy reports: equity curve vs benchmark, rolling Sharpe, drawdown, trades, parameter sensitivity, OOS/walk-forward splits. Every chart stores data series, axis units, timeframe, timezone, source, computation version and rendering spec. Charts must be accessible with alt text and readable in PDF.

## 6. Research integrity
Point-in-time datasets and as-of joins; SEC filing availability timestamps; no survivorship or look-ahead bias; split/dividend adjustments; price currency and FX consistency; missing-data flags; data licensing review. Research narrative must distinguish facts, calculations, assumptions, model interpretation, and uncertainty. Never invent citations or numerical data. Quantitative confidence requires explicit calibration; otherwise use qualitative evidence ratings.

## 7. Security and operations
Server-side secret vault/environment injection, per-user RBAC, request rate limits, prompt-injection-resistant retrieval, allowlisted tools, no LLM shell execution, immutable audit logs, retention policies, backups and restore drill, GDPR/privacy considerations, provider licensing, research-only guardrails. Stop flag pauses new runs and alerts; worker cancellation is explicit and verified. Monitor costs per model and per job, set daily/monthly budgets.

## 8. Phased implementation (Codex tickets)
### Phase 0 — Discovery and ADRs
P0-01 inspect repository and existing AlphaSense; P0-02 choose architecture and produce ADRs; P0-03 define MVP scope, acceptance criteria, data licensing assumptions.
### Phase 1 — Foundations
P1-01 monorepo and devcontainers/Compose; P1-02 backend and frontend skeleton; P1-03 PostgreSQL migrations and instrument registry; P1-04 CI/tests/observability/auth.
### Phase 2 — Data
P2-01 provider interfaces; P2-02 EOD prices + corporate actions; P2-03 equity fundamentals and filing provenance; P2-04 commodity feeds with explicit availability gaps; P2-05 snapshots/data quality tests.
### Phase 3 — Analytics
P3-01 deterministic equity fundamental metrics; P3-02 commodity fundamental templates; P3-03 technical indicators; P3-04 benchmark and scenario modules; P3-05 golden fixture tests.
### Phase 4 — AI
P4-01 provider-neutral model gateway; P4-02 config UI and model test; P4-03 structured synthesis and citations; P4-04 fallback, budget, eval harness, prompt injection tests.
### Phase 5 — Reports
P5-01 report schema and immutable revisioning; P5-02 chart registry and export; P5-03 HTML report renderer; P5-04 PDF renderer and visual regression tests; P5-05 reports archive and comparison UI.
### Phase 6 — Strategy Lab
P6-01 constrained strategy DSL; P6-02 deterministic backtesting; P6-03 OOS/walk-forward/fees; P6-04 validation and experiment registry; P6-05 paper signal monitor.
### Phase 7 — Automation
P7-01 job queue/schedules; P7-02 alerts; P7-03 budgets and kill switch; P7-04 deployment, backup and load tests.
### Phase 8 — Hardening
P8-01 security/privacy review; P8-02 data licensing review; P8-03 benchmark against hand-verified cases; P8-04 production readiness checklist.

## 9. Definition of Done per ticket
- Implementation, migration where relevant, tests, docs, and sample data.
- No hidden hardcoded credentials or vendor-specific business logic.
- `ruff`, `mypy`/`pyright`, `pytest`, frontend lint/typecheck/tests, end-to-end smoke pass.
- API contracts and fixtures versioned; metrics numerically validated.
- UI accessible/responsive, report PDF visually checked.
- Explain limitations and tradeoffs in PR description.

## 10. First instruction to Codex
You are the implementation agent for AlphaSense AI Research Platform. Read this master plan. First inspect the existing repository and document its actual stack and structure. Do not overwrite working code. Produce `docs/architecture/current-state.md`, `docs/architecture/target-state.md`, `docs/adr/0001-platform-architecture.md`, `docs/roadmap/issues.md`, and a prioritized task list with dependencies, acceptance tests, and realistic effort estimates. Identify unknown data licensing and provider costs. Do NOT implement Phase 1 until the discovery report and ADR are reviewed. Then work one ticket per branch/PR, with tests and evidence. The product is research-only: never implement broker order placement.
