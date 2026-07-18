# Demo Data Findings — First Check (data-side only)

**Date:** 2026-07-18  **Scope:** Does the data that the assistant's tools actually query
support each scenario's demo questions? Ground truth = `Crime_Intelligence_Platform_Demo_Scenarios.pdf`

- `data_generation/identifier_pool.py`. Data is synthetic, so any mismatch is fixed by
correcting the generated data (historical and/or live).

Method: ran each demo question through the **real assistant tool** (`backend/app/assistant/tools.py`)
against live Postgres / Neo4j / Pinecone, and compared the returned data to the intended
outcome. Harness: `scratchpad/dbq.py`.

## Current state census


| Fact                          | Value                                                                                       |
| ----------------------------- | ------------------------------------------------------------------------------------------- |
| Total cases (PG `CaseMaster`) | 61 (59 historical + 2 live)                                                                 |
| Live scenarios ingested       | **All four** — Scn1 (1000063), Scn2 (1000064), **Scn3 (1000065)**, **Scn4 (1000066)**       |
| Scn3/Scn4 ingested            | via direct `IngestProcessor` after two blocking fixes (see "Ingestion fixes applied")       |
| `CrimeRegisteredDate` range   | 2024-08-16 → **2026-06-26** (today = 2026-07-18)                                            |
| Pinecone vectors              | 96 (dim 1536, cosine)                                                                       |
| Neo4j                         | 61 CaseMaster, 59 Account, 13 UPIHandle, 6 Device, 4 IP, 5 Accused, 1 Wallet, 1 PhoneNumber |


Two axes to keep separate (per `identifier_pool.py`):

- **Genuine data gap** — data that should be present/correct but isn't.
- **Not ingested yet** — Scn3/Scn4 live docs + `LIVE_ONLY_IDENTIFIERS` are *supposed* to be
absent until the live upload; not a bug. Their questions can only be judged after ingestion.

---



## ITERATION 1 — Regenerate + reload (DONE, verified)

Full deterministic regen (`generate --restart`, seed 42, Bedrock `zai.glm-5`) → wipe all DBs →
migrate PG → load Neo4j → load Pinecone → re-ingest 4 live scenarios. Code fixes made:

| Fix | Where | Result (verified on reloaded data) |
|---|---|---|
| **SYS-1** narratives → `BriefFacts` | root cause: `narrative_map` empty (all 62 FIRs were placeholders); regenerated | `BriefFacts` 62/62; summaries show full MO prose + district + timeline |
| **S1-1** MO match | `export.py::write_vector_jsonl` embeds **narrative prose**, not full doc; live scn1 FIR → tier-A template | live scn1 → 3 historical scn1 at **0.89/0.88/0.88** cross-jurisdiction ✅ |
| **S1-3** convergence | `scenario_1.py` — 3 historical cases now MENTION `AGG_ACC_01` | `find_links` shows AGG shared by 3 (+live) ✅ |
| **S2-1** alias collapse | `load_neo4j_from_pg.py` — OWNS from `EXT_Uses` (many-to-many), not single `holder_entity_uid` (migrate's COALESCE dropped aliases 2&3) | `person_history("Imraan")` → 3 aliases via shared device/UPI/phone ✅ |
| **SYS-3** IR vector metadata | `write_vector_jsonl` — IR inherits case crime_type/district | populated |
| **SYS-4** temporal | `settings.demo_reference_date` (2026-06-26) in `detect_community` + specialist/agent prompts, not `NOW()` | `detect_community(days=21)` → 13-case surge cluster (was 0) ✅ |
| **legal** | ingest evidence files as `Evidence` rows | live scn1 legal = 3 green / 6 amber (§63 gap) / 4 red ✅ |
| Live IR reveals | scn3 IR → hub + freezable; scn4 IR → full device/IP pool + controller | in docs |

### All 4 scenarios verified end-to-end (live + historical, after reload + re-ingest)

| Scn | Marquee moments verified |
|---|---|
| **1 Digital Arrest** | live FIR → 3 historical by MO **0.89/0.88/0.88** cross-district · find_links → shared `AGG` across 3+live · money trail + crypto · legal 3🟢/6🟠(§63)/4🔴 · summary prose+district+timeline |
| **2 Many Names** | `person_history` → **4 aliases** incl LIVE "Imran S." via shared device/UPI/phone · escalation 2024→2026 · legal BNS 318 |
| **3 Follow Money** | bridge shared by **2 scam types** (Belagavi + live Dharwad) · hub now mentioned by live case · trace → crypto cash-out + freezable · PMLA 5🟢 (proceeds+layering) |
| **4 The Surge** | community 22 cases → **live joins 15-case ring** · surge `days=21` → 13-case cluster (reference date) · legal 5🟢 · device pool |

### Iteration 2 progress
- **SYS-2 geo + victim — DONE.** `processor.py::_enrich_case_geo_victim` now writes `EXT_CaseGeo`
  (district from the case's PoliceStation; lat/long/pincode from the district centroid of existing
  cases) and mirrors the complainant to a `Victim` row, on every live FIR ingest. Verified: all 4
  live cases show their district (scn1/2/4 Bengaluru Urban, scn3 Dharwad) + a victim; summaries no
  longer say "district unknown / victims none". Wow moments intact after re-ingest.
  - Also fixed `reset_demo_data.py` to delete `EXT_CaseGeo`/`EXT_SubEvent` before `CaseMaster`
    (they now hold demo rows → FK violation otherwise).
- **Scn4 org chart — DONE.** The live scn4 IR now carries a deterministic `OPERATOR ROSTER` block
  (`name | role | IMEI`), and `processor.py::_enrich_operator_roster` parses it into **role-typed
  Accused nodes** (caller/mule_handler/recruiter/controller), each `OWNS→` its device/UPI + `INVOLVES`
  the case. The Network specialist's graph schema card now teaches the `role` property + the
  org-chart query. Verified: `run_cypher_read` returns all 6 operators with roles + devices —
  Ravi V/Deepak N (caller), Suresh M/Harish K (mule_handler), Venkat R (recruiter), Ring Controller.
  (Robust: no LLM extraction of the roster; parsed from the doc. Docs synced to `frontend/src/assets/live_demo`.)

- **Scn3 money tuning — DONE.** Rewrote the `scenario_3.py` ring: 6 collector accounts now pour
  into `HUB_ACC_03` (7 inbound / ₹28L → it ranks **#1 busiest aggregation account** in the ring,
  Q3), and the two freezable mules (…013/…014) accumulate several sub-₹1L tranches to **exactly
  ₹6.2L** with no outbound (Q1). Verified after reload: `trace_money_flow` reports "FREEZABLE Rs 6.20
  lakh" + crypto cash-out; a ring-scoped centrality query puts the hub top.

### Still deferred (polish — core wow moments work)
- **SYS-2 `EXT_SubEvent` (live timeline):** not derivable yet — the extractor leaves `IncidentFromDate`/
  `ToDate` NULL and the live FIR prose has no structured sub-events. Needs a header regex to pull the
  offence window + a minimal timeline. Historical cases have full timelines; only live is sparse.
- **scn4 device_pool.csv mislabel:** the CSV gets classified `EVIDENCE_BANK_STATEMENT` by the
  regex-fallback classifier, so each IMEI also gets a stray `:BankStatement` node with a *different*
  entity_uid (duplicate of the `:Device` node). Community/org-chart work via the `:Device` nodes;
  the duplicate is cosmetic clutter. Fix = a device-dump doc_type/classifier hint.
- **scn2 phone-label glitch:** shared PhoneNumber node displays "Investment Manager (Imran S.)" not
  the number; linkage works, label is wrong.
- **extraction robustness:** bedrock structured-output falls back to regex on CSV-heavy docs;
  `LIVE_SCN4_FIR` uses the deterministic fallback (content filter). Both work; not pretty.
- **scn2 label glitch:** the shared PhoneNumber node's `display_name` is "Investment Manager (Imran S.)"
  instead of the number `9611234567` (extraction mislabelled holder as display). Linkage works; label is wrong.
- **scn4 org chart:** operator roster is now in the IR text but extraction doesn't turn "Ravi V — caller"
  prose into role-typed Person nodes yet.
- **scn3 amounts:** hub is mentioned (enters graph) but ranking it #1 by centrality + exact ₹6.2L
  freezable need historical transaction-volume tuning in `scenario_3.py`.
- **extraction robustness:** bedrock structured-output fell back to regex on scn3/scn4 CSV-heavy docs
  (worked, but flaky); `LIVE_SCN4_FIR` hit a Bedrock content filter → deterministic fallback (identifiers
  preserved; fine for scn4 whose wow is graph, not MO).
- **`local_invoke` STALE_TIMEOUT:** the backend Ingest-screen path; I ingest via direct `IngestProcessor`.

## ITERATION 3 — Assistant analysis + end-to-end testing

Analysed the overhauled assistant and executed all 4 scenarios' marquee questions through the
**actual supervisor graph** (capturing plan + reasoning trail + artifacts + answer).

**Architecture (matches the intended design, scalable claim holds):** supervisor LLM planner →
parallel `Send` fan-out to 5 specialist ReAct subgraphs → synthesize; specialists carry **generic
DB tools** + **skill-as-tool playbooks** (`skills/playbooks/*/SKILL.md`, description triggers, body
is the workflow, assigned per-agent via frontmatter). Adding a `SKILL.md` + `agents:` line = a new
analysis path with the same architecture. Reference `cogentiq-assistant-byod-backend` uses the same
pattern at heavier production scale (sandbox/Celery/MCP) — not needed here.

**Marquee questions — all pass after fixes:** scn1 summary+timeline ✅ · scn1 MO-match (0.90
cross-district + Find-Links action) ✅ · scn2 alias-collapse (4 aliases) ✅ · scn3 money-trail
(graph + ₹6.2L freezable + crypto) ✅ · scn4 org-chart (6 role-typed operators) ✅ · scn4
organised-ring (verdict + 15-case cluster) ✅. Artifact **formats** are correct (graph nodes carry
`type`+`properties`, tables `columns`+`rows`, documents text; camelCase nested / snake_case frames).

**Assistant bugs found + fixed:**
1. **Run crash on recursion limit** — one specialist exhausting its step budget raised
   `GraphRecursionError` that propagated and killed the *entire* run. Now caught in
   `_run_specialist_node` → degrades to a partial finding; the other specialists + answer survive.
2. **scn4 org chart didn't converge / crashed** — no guiding skill, so the network specialist
   over-explored to the limit. Added `operator-org-chart` SKILL.md (one deterministic Cypher →
   the role map). Converges in ~1 call.
3. **scn2 alias collapse didn't use `person_history`** — the model defaulted to raw Cypher and
   confused `case_id` with `entity_uid`. Fixed: prescriptive Network prompt (explicit if-then tool
   mapping), schema card now documents `case_id` + how to match a case node, `offender-profile`
   skill finds the accused name first.
4. **Over-exploration exhausted the budget** — the conv LLM (zai.glm-5) runs the right tool AND
   many confirming queries before answering. Bumped `MAX_SPECIALIST_ITERATIONS` 10 → 16 so it can
   explore *and* compose; runaways caught by fix #1.
5. **Shared-account `:Account` node destroyed across demo resets** — `_load_graph` overwrote
   `n.case_id = $case_id` on shared historical nodes, so the case_id-based `demo_scenario_reset`
   deleted them; the live re-ingest then re-made them as `:MentionedAccount` (no `:Account`), and
   `trace_money_flow` (matches `:Account`) returned "no accounts". Fixed with
   `n.case_id = coalesce(n.case_id, $case_id)` (same guard `origin` already had); repaired the live
   data by re-running `load_neo4j_from_pg`.

**Observations (not blocking; per your "keep all artifacts" choice):** the model over-queries
(Financial ran ~13 SQL after `trace_money_flow`; Network ~37 Cypher for the ring) — works but noisy
and slow; the Financial/MO specialists could get the same prescriptive prompt Network now has.
Narrative-quality nits: some historical FIRs cite IPC §419/420 (not BNS) and one frames the AGG
account as an "RBI circular reference number".

**Also fixed this iteration — scn4 `device_pool.csv` mislabel:** added an `EVIDENCE_DEVICE_DUMP`
doc_type + `DeviceRecord` schema (IMEI→Device), so the device pool no longer mis-extracts IMEIs as
`:BankStatement` account nodes; the IMEI is now one merged `:Device:MentionedDevice:DeviceRecord`
node. (Demonstrates the "add a schema for a new evidence type" scalability.) Also fixed
`reset_demo_data.py` to delete `EXT_CaseGeo`/`EXT_SubEvent` before `CaseMaster` (FK order).

## Ingestion fixes applied (were blocking Scn3/Scn4 ingestion)

Two blockers stopped the live pipeline from ingesting Scn3/Scn4. Both fixed so ingestion completes:

- **FIX-1 — extraction LLM was failing.** `DATA_INGESTION_LLM` defaulted to `zoho` (QuickML GLM),
which now returns HTTP 400 `PATTERN_NOT_MATCHED` on every call; the openai fallback returned
refusals. Extraction produced garbage/empty entities. **Set** `DATA_INGESTION_LLM=anthropic`
in `.env` (claude-sonnet-5, key already present) → clean extraction. *(Decision for you: keep anthropic, or repair the zoho GLM request format.)  -- User Note: in the .env, i have changed the DATA_INGESTION_LLM to bedrock. the bedrock model_ids are also given in the env file in different configs.*
- **FIX-2 — Phase B crashed on unknown accused.** `processor.py::_write_person_row` skipped None
fields, so an FIR that names no offender (money-laundering/task-scam) left the NOT-NULL
`AccusedName` absent → `NotNullViolation`, aborting the whole load. Added a default of "Unknown"
(matches the historical convention) at the shared write site.

*Note:* the HTTP `local_invoke` ingestion path (the backend's `INGEST_LOCAL_INVOKE` thread) went
`STALE_TIMEOUT` ("job never started") — a separate issue. I ingested by driving `IngestProcessor`
directly (same pipeline code, same data), which is the sanctioned local path. The local_invoke
thread should be investigated before a live demo relies on the Ingest screen.

## SYSTEMIC issues (hit multiple scenarios)



### SYS-1 — Historical narratives are missing from Postgres `BriefFacts` (59/61 cases null) 🔴

Only the 2 live cases have `CaseMaster.BriefFacts`; all 59 historical cases are `NULL`.
The FIR narratives *do* exist in Pinecone (`historical::<id>::FIR` present) but were never
written back to PG.

- **Breaks:** `get_case_summary` on any historical case → "BRIEF FACTS: (none recorded)".
`find_similar_cases(case_ref=<historical>)` uses `case.brieffacts` as the query text → returns
"no narrative". Any drill-into a matched historical case shows an empty case.
- **Fix (data):** during generation/load, write the FIR narrative into `CaseMaster.BriefFacts`
for every case (the text already exists — it's what was embedded). Check `export.py` /
`db_loader.py` / `migrate_sqlite_to_pg.py` — the narrative column is being dropped on the
SQL path.



### SYS-2 — Live-case ingestion does not populate geo / timeline / evidence / entity-ownership 🔴

The two ingested live cases (1000063, 1000064) are missing structured data that all
historical cases have:


| Table / edge                                 | Historical          | Live 1000063/1000064                                                                                                             |
| -------------------------------------------- | ------------------- | -------------------------------------------------------------------------------------------------------------------------------- |
| `EXT_CaseGeo` (district, pincode)            | 59/59 rows          | **0 rows (all 4 live cases)** → district "unknown"                                                                               |
| `EXT_SubEvent` (timeline)                    | 274 rows / 59 cases | **0 (all 4 live cases)** → no timeline                                                                                           |
| `Evidence` (uploaded docs)                   | present             | **now written when evidence files are uploaded** (Scn3/Scn4 = 3 rows each; Scn1/Scn2 = 0 because they were ingested FIR+IR only) |
| `Victim` rows                                | present             | **0 (all 4 live cases)** → "victims: none recorded" (e.g. Scn3 victim "Sandeep Traders" missing)                                 |
| Accused/entities `OWNS` identifiers in graph | yes                 | **live accused owns nothing**                                                                                                    |


- **Breaks:** Scn1 Q1 "case card + 2-day timeline" (empty timeline, unknown district);
Scn2 alias resolution (live accused not linked to its own IMEI/UPI/phone); the legal
checklist §63 derivation which reads `Evidence`; every spatial/hotspot analysis (no district
on the case the officer is actually working).
- **Important:** this is the **live ingestion pipeline**, not the historical loader — wiping and
reloading historical data will NOT fix it. The pipeline (`catalyst_functions/ingest_processor/pipeline/processor.py`)
must write `EXT_CaseGeo`, `EXT_SubEvent`, `Evidence`, `Victim`, and entity `OWNS` edges. Re-verify
Scn3/Scn4 here after they're ingested.



### SYS-3 — Pinecone metadata incomplete on IR and demo vectors 🟡 (latent)

FIR vectors carry `crime_type`/`district`; **IR vectors have empty** `crime_type` **and** `district`,
and the **demo/live FIR vector has** `crime_type=None, district=None`.

- **Note:** verified that `find_similar_cases` does **not** filter on vector metadata (pure
cosine top-k, then re-joins PG) — so this does **not** currently break the MO search. It's
latent: the spec wants filtered MO search, and any future/other filter on these fields drops
IR + live docs. Lower priority than first assumed.
- **Fix (data):** populate `crime_type`, `district`, `date_registered` on every vector's
metadata at embed time (both historical loader and the live ingestion embed step).



### SYS-4 — Temporal drift: newest case is 22 days old, breaks all "recent window" questions 🔴

`MAX(CrimeRegisteredDate) = 2026-06-26`, today = 2026-07-18 → **zero cases in the last 21 days**.

- **Breaks:** Scn4 Q1 "surge in the last 21 days" and Q2 `detect_community(days=21)` (uses
`NOW() - 21 days`) return nothing; any "this quarter/last month" trend under-counts.
- **Fix (data):** anchor the burst/surge dates to a rolling "now" (generate recent cases
relative to run date, or shift the Scn4 cluster + live FIRs into the last ~14 days). Don't
hard-code absolute dates for the surge cluster.
- User Note: the actual demo is quite some time away, we can not compare with todays date everytime, need to fix our date so that the temporal analysis can be done seamlessly. regenerate the data now, but think about how to use a fixed date for compare instead of today's date.

---



## Scenario 1 — Digital Arrest (ingested; case 1000063)

Historical facts are correctly planted in PG (3 collection accounts in Mysuru/Mangaluru/Hubballi
→ `AGG_ACC_01` 9842017633250001; cases 1000001/2/3 exist). The failures are in the graph
projection and the vector narratives.


| #   | Question / tool                         | Result                                                                        | Verdict    |
| --- | --------------------------------------- | ----------------------------------------------------------------------------- | ---------- |
| Q1  | timeline → `get_case_summary`           | summary OK, but **district unknown, no timeline, no victim/evidence** (SYS-2) | 🟠 partial |
| Q2  | money speed → `trace_money_flow`        | see S1-2                                                                      | 🟠         |
| Q3  | similar MO → `find_similar_cases`       | see S1-1                                                                      | 🔴         |
| Q4  | find links → `find_links_between_cases` | see S1-3                                                                      | 🔴         |
| Q5  | legal gaps → `legal_checklist`          | **runs, but 0 green / 13 RED** — see S1-4                                     | 🔴         |




### S1-1 — MO narratives are NOT near-duplicate → similar-case search returns the wrong cases 🔴

Querying Pinecone with the live FIR narrative, the 3 intended historical digital-arrest cases
rank **#38 (0.697), #50 (0.676), #57 (0.668)** — *below* unrelated task-scam / OTP / phishing
cases that fill the top 10. `find_similar_cases` returns OTP/Phishing/SIM-swap, not the
Mysuru/Mangaluru/Hubballi digital-arrest ring.

- **Spec wants:** those 3 as the **top 3 at ~0.92/0.89/0.86**, cross-jurisdiction.
- **Root cause (confirmed by reading the docs):** two compounding problems.
  1. **Different document templates.** Historical FIRs use a structured KSP header format
    (`KARNATAKA STATE POLICE / FIRST INFORMATION REPORT / Crime No … / Police Station …`,
     accused "Unknown"); the live FIR is free prose. The embedding is over the whole doc, so the
     boilerplate divergence alone depresses cosine even when the MO matches.
  2. The narrative bodies were LLM-generated independently with too much variation; the spec rule
    "same-MO cases share near-duplicate text" was not honoured for this cluster.
- **Fix (data):** (a) embed a normalised **narrative-only** field (strip header boilerplate) so
format doesn't dominate similarity, and/or (b) regenerate the live Scn1 FIR + the 3 historical
scn1 FIR narratives from one shared MO template (same script phrases: CBI/TRAI/Skype custody,
"RBI verification"), varying only surface details. Keep the decoy (`SCN1_DECOY`,
Google Meet/Hassan) deliberately dissimilar so the confidence threshold still shows.



### S1-2 — Live victim has no own account/outbound transfer; money trail shows the aggregate inbound, freezable = whole ₹54L 🟠

`trace_money_flow(1000063)` → "3 transfers totalling ₹54 lakh … ₹54 lakh sitting still (freezable)"
in `AGG_ACC_01`. The 3 transfers are the **historical** Mysuru/Mangaluru/Hubballi collection
accounts flowing *into* AGG (the live case mentions AGG directly, has no outbound, so the tool
falls back to inbound-to-seed).

- **Spec wants:** the **victim's** account → outward trail, with **~₹9.3L** flagged freezable
(not the entire sum), loss ₹42L.
- **Root cause:** the live Scn1 case has no Bengaluru victim collection account and no victim→AGG
transaction; it only points at AGG. The **₹54L is the three *historical* cases' inbound sum
(21+18+15 lakh)** surfacing because the live case has no outbound of its own — it is **not** a
live-victim ledger of ₹54L. The live FIR narrative states ₹42L loss but no matching transaction
exists.
- **Fix (data):** add the **live victim's own collection account** plus a
victim→collection→AGG transaction path (minute-level timestamps, total ≈₹42L), and make only a
subset (~₹9.3L) freezable (i.e. some downstream hops move on, the freezable accounts don't).
Do **not** just "reconcile the ₹54L number" — the fix is to give the live victim a real trail.



### S1-3 — "Four cases → one account" convergence is invisible to `find_links` 🔴

`find_links_between_cases` matches a shared **MENTIONS** node:
`(c1)-[:MENTIONS]->(o)<-[:MENTIONS]-(c2)`. But in the graph each historical case mentions only
its **own** collection account (1000001→…011, 1000002→…022, 1000003→…033) and the live case
mentions **AGG** directly. `AGG_ACC_01` is mentioned by only 1 case → **find_links returns
nothing**. The convergence exists only as transaction edges (money trail), which this tool
doesn't traverse.

- **Spec wants:** all four cases share the aggregation account node.
- **Fix — choose one:**
  - **(A, data, recommended)** add `EXT_Mentions` / graph `MENTIONS` edges from cases
  1000001/1000002/1000003 (and the live case) to `AGG_ACC_01`, so the shared node is real.
  - **(B, tool)** extend `find_links_between_cases` to also report a common account reached within
  1–2 transaction hops. (Out of "data-only" scope; note for later.)
  - Both S1-1 and S1-3 must be fixed together: the Find-Links flow first calls
  `find_similar_cases` to get the refs, so if similar returns the wrong cases, link analysis
  runs on the wrong set regardless.



### S1-4 — Legal checklist returns all-RED because the case has no `Evidence` rows 🔴

`legal_checklist(1000063)` runs correctly (the legal chain tables are fully populated —
`EXT_SectionMap` 10, `EXT_LegalElement` 29, `EXT_ElementSatisfiedBy` 28, `EXT_EvidenceType` 15,
`EXT_Precedent` 12) but returns **0 green / 0 amber / 13 RED**, "evidence on file: none
classifiable, BSA s63 certificate: NOT on file". `_classify_evidence` reads the `Evidence`
table, which is empty for the live case (SYS-2), so every element is "missing".

- **Spec wants:** mostly green, messaging screenshots **amber** ("needs §63 BSA certificate"),
controller link amber. The Scn1 evidence folder deliberately ships **no** §63 cert
(`README_EVIDENCE_GAP.txt`) — that absence is the intended amber.
- **Root cause:** the uploaded evidence files (`transaction_ledger.csv`, `call_log.csv`,
`messaging_screenshot_1.html`) are never recorded as `Evidence` rows during ingestion (SYS-2).
The classifier keys off `Evidence.doc_type`/`original_filename`, so with no rows nothing is
green.
- **Fix (data/pipeline):** ingestion must insert one `Evidence` row per uploaded file (doc_type +
original_filename), including the §63 certificate files where present (Scn2/3/4 ship
`bsa_63_certificate.txt`). Then bank statement → green, screenshots → amber (no §63 for scn1),
matching the spec. **This is the same fix that unblocks the legal question in all four scenarios.**
- *Secondary:* the precedent surfaced was a *conviction* (Vikas Garg); the spec's amber wants a
§63 **acquittal** precedent tied to the electronic-evidence element. Tune `EXT_Precedent.ElementTurnedOn`
so a missing-certificate acquittal is cited for the screenshot element.

---



## Scenario 2 — Many Names, One Man (ingested; case 1000064)

The 4 alias **cases** exist in SQL with escalating dates and the right alias names —
1000005 Imraan Sheikh (loan_app, 2024-08), 1000006 I. Shaikh (otp, 2025-03), 1000007 Imran
Shek (job, 2025-11), 1000064 Imran S. (investment, 2026-06). Escalation data is present.
The **graph linkage that collapses them is missing.**

### S2-1 — Shared IMEI/UPI/phone are owned by only ONE alias node → alias resolution fails 🔴

`person_history("Imran")` → "No person matching 'Imran' owns identifiers we can link on."
In the graph only **"Imraan Sheikh"** (case 1000005) `OWNS` the shared identifiers
(`imran.transactions@axl`, IMEI `351756078901234`, phone `9611234567`). "I. Shaikh",
"Imran Shek" and the live "Imran S." **own nothing**, and "I. Shaikh" has no linked-identifier
graph node at all.

- **Spec wants:** all 4 alias nodes tied together by the shared device+UPI+phone → "92% same
person" with the shared identifiers shown as proof.
- **Root causes:**
  1. Only one alias was given `OWNS`/`USES` edges to the shared identifiers; the others weren't.
  2. The **live** accused "Imran S." mentions the shared IMEI/UPI/phone in its FIR text but the
    ingestion created no `OWNS` edge (SYS-2).
- **Fix (data):** in the historical scn2 planting, give **every** alias Accused node `OWNS` edges
to the same `DEV_IMEI_02`/`UPI_02`/`PHONE_02` nodes. Ensure the live ingestion links the
extracted accused to those same (existing) identifier nodes so it merges, not duplicates.



### S2-2 — Name blocking misses "Imraan" (double-a) 🟠

`person_history` seeds on `toLower(display_name) CONTAINS toLower($name)`. "imraan" does **not**
contain "imran", so a query for "Imran" skips the only alias that currently owns the identifiers.
Even after S2-1, exact-substring name blocking is fragile across alias spellings.

- **Fix:** this is primarily solved by S2-1 (link via identifiers, not name). Optionally the tool
should block on shared identifiers of the *live case's* accused rather than a free-text name.
Note for the tool layer; not a data fix.



### S2-3 — Escalation chain depends on person resolution, which currently fails 🟠

The escalation timeline (Q3) is correct in SQL but the assistant reaches it *via* the resolved
person from the graph. Because S2-1 fails, the chain never gets the case set. Fixing S2-1 unblocks
Q3. Verify amounts actually escalate (frontend copy says ₹1.5L→₹8L; PDF says ₹15L live — reconcile).

---



## Scenario 3 — Follow the Money (INGESTED; case 1000065) — tested


| #   | Question / tool                                       | Result                                                                                       | Verdict               |
| --- | ----------------------------------------------------- | -------------------------------------------------------------------------------------------- | --------------------- |
| Q1  | trace money → `trace_money_flow`                      | 9 transfers, ₹19.2L, 27 min, **crypto USDT cash-out**, freezable flagged                     | 🟠 works, amounts off |
| Q2  | bridge → `find_links_between_cases` / `expand_entity` | **bridge** `5530123456789001` **shared by 2 cases** (Belagavi digital-arrest + live Dharwad) | ✅                     |
| Q3  | ledger+KYC hub → `detect_community`                   | **hub** `5530123456789002` **(Somashekar T) mentioned by 0 cases → won't rank**              | 🔴                    |
| Q4  | PMLA → `legal_checklist`                              | **5 green / 6 red**; PMLA proceeds + layering GREEN, §63 on file                             | ✅                     |




### S3-1 — Bridge + PMLA work; the live→historical merge succeeded 🎉

The whole point of Scn3 works: `trace_money_flow` shows the layering path to a USDT wallet and
flags freezable funds; `find_links` confirms the bridge account is shared across the historical
Belagavi digital-arrest and the live Dharwad UPI-fraud — two different scam types. The live case's
mention of `5530123456789001` merged onto the existing historical Account node (entity_uid join).
Legal shows PMLA proceeds-of-crime and layering as green with the §63 certificate on file.

### S3-2 — Freezable amount and victim loss don't match the spec numbers 🟠

Freezable = **₹1.8L** (mules …013/…014, ₹90k each); spec says **₹6.2L**. Trail total **₹19.2L**;
victim loss is **₹28L**. The live victim's own ₹28L path is barely represented — the trail is
essentially the *historical* Belagavi ring (dated 2026-02-05), not the live Dharwad money.

- **Fix (data):** in the live transaction dump (`transaction_ledger.csv`) give the Dharwad victim a
₹28L outbound path through the ring, and size the freezable tranches (…013/…014 + others) to ≈₹6.2L.



### S3-3 — Hub account has no case mention, so "rank the hub" fails 🔴

`5530123456789002` (Somashekar T, the highest-volume aggregation hub) is **mentioned by 0 cases**
and isn't prominent in the transaction ring, so `detect_community`/centrality won't surface it as
#1. Q3 ("rank hub accounts") produces nothing.

- **Fix (data):** route many mule→hub transactions through `5530123456789002` (so degree/PageRank
ranks it top), and have the live IR mention it so it enters the graph. The KYC name is already set.

---



## Scenario 4 — The Surge (INGESTED; case 1000066) — tested


| #   | Question / tool                              | Result                                                                                | Verdict     |
| --- | -------------------------------------------- | ------------------------------------------------------------------------------------- | ----------- |
| Q1  | pattern/surge → `find_similar_cases` + count | **0 task-scam cases in last 21 days** (15 in 60d)                                     | 🔴 temporal |
| Q2  | organized ring → `detect_community`          | **live case joined the largest cluster (14 of 21)** sharing mule accts/UPIs/IP/device | ✅           |
| Q3  | hotspots/IP co-location                      | only **1 of 4 IPs** ingested for live; heatmap needs lat/long (SYS-2 geo missing)     | 🟠 partial  |
| Q4  | org chart → operators                        | **no operators ingested** — see S4-2                                                  | 🔴          |
| Q5  | legal → `legal_checklist`                    | **5 green / 2 red**; device dump + screenshot + §63 all green                         | ✅           |




### S4-1 — Surge window is empty (SYS-4) 🔴

`task-scam` cases in the last 21 days = **0** (the live FIR is dated in the past too). The
"emerging pattern, last 21 days" alert and `detect_community(days=21)` return nothing.

- **Fix (data):** shift the ~18 task-scam burst FIRs **and the live Scn4 FIR** into the last
~14–21 days relative to the demo date (anchor to rolling "now").



### S4-2 — Org chart impossible: the operator roster isn't in the source documents 🔴

The live Scn4 IR (`investigation_report.txt`) names only **one IMEI + one IP** and **no operators**;
`device_pool.csv` lists 5 IMEIs/4 IPs but **no operator names or roles**. So although
`identifier_pool.py` defines `SCN4_OPERATORS` (Ravi V/Suresh M/… with roles) and
`SCN4_CONTROLLER_*`, none of it is in the documents the pipeline reads. Result: case 1000066 has
one "Unknown" accused, mentions **1 device**, and no controller — the org chart (Q4) can't be built.

- **Fix (data):** regenerate the live Scn4 IR + `device_pool.csv` to actually contain the operator
roster (name, role, the IMEI/IP each uses) and the controller account/UPI
(`4440988776655099` / `ring.ctrl04@ybl`), so extraction yields role-typed Person nodes.
- **Fix (pipeline, secondary):** CSV evidence rows aren't turned into per-row entity mentions — only
what the IR narrative explicitly names is extracted. The 5-device / 4-IP pool won't ingest from a
CSV until the extractor reads tabular evidence.



### S4-3 — Community detection + legal are solid ✅

`detect_community(crime_type="task")` correctly pulls the live case into the 14-case ring on shared
infrastructure. Legal is 5 green / 2 red with the device-dump §63 certificate recognised.

---



## Priority for the wipe-and-reload

**Historical-data fixes (regenerate + reload):**

1. SYS-1 write narratives to `CaseMaster.BriefFacts` for all cases.
2. SYS-4 / S4-1 anchor surge + recent dates to a rolling "now".
3. S1-1 near-duplicate MO narratives for the Scn1 digital-arrest cluster.
4. S1-3 (A) plant `MENTIONS` edges from all 4 Scn1 cases → `AGG_ACC_01`.
5. S2-1 give all 4 Scn2 alias nodes `OWNS` edges to the shared IMEI/UPI/phone.
6. SYS-3 populate vector metadata (crime_type/district/date_registered) on IR + all docs.
7. S1-2 give the live Scn1 victim a collection account + graded freezable subset (~₹9.3L).

**Live-ingestion-pipeline fixes (independent of reload — needed for every live case):**
8. SYS-2 populate `EXT_CaseGeo` (district+pincode+lat/long), `EXT_SubEvent` (timeline), `Victim`,
   and entity `OWNS` edges during ingestion. `Evidence` rows now write when evidence files are
   uploaded — the legal question (Q5/Phase 3) works for Scn3/Scn4 because their evidence files were
   included. **Re-ingest Scn1 + Scn2 WITH their evidence files** (they were ingested FIR+IR only, so
   legal is all-red) — same flow, add the `evidence/scenario_{1,2}` files.
9. FIX-2 (done) unknown-accused "Unknown" default; investigate the `local_invoke` STALE_TIMEOUT so
   the Ingest-screen path works, not just the direct driver.
10. CSV/tabular evidence isn't extracted into entities (S4-2) — the device/IP pool won't ingest.

**Scenario-specific data tuning (regenerate live docs):**
11. S3-2 size the Scn3 live transaction dump to the ₹28L victim path + ≈₹6.2L freezable.
12. S3-3 route mule→hub transactions through `5530123456789002` so it ranks #1; have the live IR mention it.
13. S4-2 put the operator roster + controller into the Scn4 live IR / `device_pool.csv`.
14. S4-1 / SYS-4 shift the Scn4 surge cluster + live FIR into the last ~14–21 days.

**Confirmed working after ingest (no data change needed):** Scn3 money-trail + crypto cash-out,
Scn3 bridge (2-scam shared account), Scn3 PMLA legal, Scn4 community detection, Scn4 legal.
The live→historical `entity_uid` merge works (Scn3 bridge proves it).

*Data quality nits:* narrative placeholders ("[Insert Date]"), Scn1 narrative date "15th Oct 2023"
vs registered 2026-06-26, amount ₹42L (narrative) vs ₹54L (ledger).