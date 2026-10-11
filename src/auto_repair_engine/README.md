# Auto repair engine experiments

This folder contains thirty concrete simulator implementations of the E01–E30 architectures in the design brief. It is a fictional local demo. The sample numbers, hourly rate, rule packs, approvals, and operation timings are invented test data; they are not shop prices, measured repair times, or validated estimates.

## Shared contract

Python functions and the TypeScript browser function use the same snake_case JSON keys: `scenario_input`, `rule_pack`, `labor_result`, `engine_result`, `engine_id`, `rule_version`, `operation_id`, `person_count`, and `duration_hours`. Every engine returns `engine_id`, `rule_version`, `status`, `labor`, `trace`, `operation_keys`, and `approvals`. Labor uses `person_hours` and `elapsed_hours` ranges (`low`, `typical`, `high`), operation `breakdown` rows with `hours`, `reason`, and `status`, and an `unknowns` list.

Required gaps stop calculation: total and affected-line ranges become null with `missing-required`; unknown never means zero. A confirmed nonbinding wait contributes zero person-hours and its elapsed duration only. Waiting, elapsed time, worker person-hours, and nonbillable work remain separate. Conditional ranges stay conditional until a person approves them. Every returned result retains the engine and rule version. The fictional common fixture in `contract.py` includes both an unresolved rotor scenario and a separately human-approved range variant. The approved baseline is E10's 2.0 gross minus 0.3 shared overlap, then minus included transport 0.12, then plus two-person handling 0.20 and wash 0.10: person-hours 1.88/2.13/2.38. Elapsed work also includes one-person handling 0.10, wash 0.10, and the 0.5 snow melting and 0.25 penetrant waits, for 2.53/2.78/3.03. `parts_wait` is zero only because the fictional stock check is confirmed.

## Run locally

From the repository root:

```sh
PYTHONPATH=src python3 -m unittest discover -s src -t src -p 'test_*.py'
node --experimental-strip-types --test src/auto_repair_engine/browser.test.mjs
PYTHONPATH=src python3 -m auto_repair_engine.api
```

The API uses FastAPI when installed and stores snapshots in a local SQLite file. No external price API, cloud service, customer data, or real repair database is required. The unified workflow is the default in the web engine selector; it composes E13 schema questions, E07 strict validation, E06 fictional approved rules (or a supplied E02 approved pack), E21 evidence approvals, E18 trace-tree verification over applied labor rows, E28-style server recomputation/idempotent SQLite save, and E29 version-pinned offline snapshots. Use **統合版（推奨）**, select the fictional approved rotor fixture for a complete example, calculate, review trace, enter a confirmation actor/reason, save, then reload from SQLite. The separate E01–E30 selector and all-30 comparison remain available. `POST /api/integrated/evaluate` applies explicitly confirmed schema answers; `GET /api/integrated/schema` returns the intake schema; `POST /api/engines/integrated/calculate` calculates; `POST /api/estimates` with `engine_id: integrated` saves with server recomputation and an optional idempotency key. `browser.ts` and its served `browser.mjs` counterpart implement E27 as a pure function. Node 24 can execute the typed source directly with native type stripping. The page can calculate E27 locally, queue fictional snapshots in IndexedDB, and reload estimates from SQLite. E28 recomputes proposals on the server and accepts an optional idempotency key for atomic duplicate-safe saves; a repeated key with changed content returns a conflict. E29 pins queued snapshots to a rule version and leaves version conflicts pending until an explicit, audited choice. E30 accepts a manual basis only with person-hour unit, definition, source, and fictional-only permission; when absent it uses the approved fictional process baseline.

## Evidence

`review-records.json` records the actual implementer and two independent reviewer IDs and their findings for each E item. It distinguishes tests executed from checks that were only reviewed. No entry implies real-shop validation.
