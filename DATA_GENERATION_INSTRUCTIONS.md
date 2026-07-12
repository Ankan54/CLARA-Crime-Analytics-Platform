# Synthetic Data Generation Instructions
## Karnataka State Police Datathon 2026 — Crime Intelligence Platform

**Audience:** a coding agent that will write the generator scripts.
**Goal:** produce a small, fully-synthetic but tightly-engineered dataset that makes the four demo scenarios work end-to-end, and gives the graph, vector and SQL stores enough realistic volume to show network analysis, similar-case search, temporal/spatial analytics and the legal checklist.

**Scope:** cyber crime and financial crime in India (Karnataka context). All case-level data is fabricated. The legal layer (statutes, precedents) is real and must be attributed.

---

## 0. Read this first — the one idea that governs everything

The demos only work if specific records share specific identifiers **by construction**. If you generate cases independently and randomly, the intended links will not form and accidental ones will.

> **Build the shared identifier pool FIRST (Section 5), then attach cases to it.** Identifiers (accounts, IMEIs, UPIs, phones, IPs, wallets) are the glue. Everything else hangs off them.

Two kinds of data, kept strictly separate:
- **Historical data** — pre-loaded into all three stores before the demo. This is the "memory" of the platform.
- **Live demo data** — 4 FIRs + 4 investigation reports, **held back as input files only**, NOT loaded into any store. They are uploaded on stage to show the ingestion pipeline working and to trigger the "links light up live" moments.

---

## 1. Non-negotiable principles

1. **Engineer the patterns, don't hope for them.** Convergence, alias overlap, layering velocity, dormancy, the recent surge, and the operator community are all scripted deliberately.
2. **Plant realistic decoys.** Include a handful of *near-miss* links the system must **correctly reject** — e.g. two people with a coincidentally shared name but no shared identifier; two cases with a similar but not identical MO. This proves the demo isn't rigged and makes the entity-resolution confidence threshold visible.
3. **Time and place are mandatory fields, never optional.** Every transaction needs a minute-level timestamp; every account an open-date + activity history + branch district; every FIR a registered date, offence date, district and pincode (and lat/long); every IP a geolocation. Without these the temporal/spatial demos cannot run.
4. **Two documents per enriched case.** The FIR seeds entities + the MO narrative; the investigation report carries the "reveal" (KYC name, IMEI, CDR, device dump) that deepens the graph.
5. **Real vs synthetic split.** Statutes and the cited precedents are real and attributed. All FIRs, persons, accounts, devices and transactions are synthetic and must be labelled as such.
6. **Cross-store IDs.** Every graph case node stores a `vector_id`; every vector record stores its `node_id` / `fir_id`. These must match exactly (Section 13).
7. **Output a planted-links manifest** documenting every intended link, for validation and for the demo script.

---

## 2. Output structure & formats

Produce this folder layout:

```
/output
  /historical                 # PRE-LOADED into the stores
    /sql                       # relational seed (system of record)
      firs.csv
      investigation_reports.csv
      persons.csv
      accounts.csv
      transactions.csv
      objects.csv              # phones, devices, upis, ips, wallets
      reference/ (districts, police_stations, banks, crime_types)
    /graph                     # Neo4j load files
      nodes_*.csv              # one per node label
      rels_*.csv               # one per relationship type
      load.cypher              # OR neo4j-admin import script
    /vector                    # documents to embed
      narratives.jsonl         # {id, fir_id/node_id, lang, text, metadata}
    /legal                     # REAL curated layer (Section 10)
      sections.csv, legal_elements.csv, evidence_types.csv, precedents.csv
      legal_rels.csv
  /live_demo                   # HELD BACK — uploaded on stage, NOT pre-loaded
    /scenario_1 ... /scenario_4
      fir.(pdf|txt) + fir.kn.(pdf|txt)        # FIR document(s)
      investigation_report.(pdf|txt)          # the "reveal" document
  /manifest
    planted_links.md           # every intended link, by scenario
    data_dictionary.md         # field-level schema reference
    validation_report.md       # results of the Section 14 checks
```

**Formats:** CSV/JSON for the stores. Live-demo documents in a format the ingestion pipeline accepts (plain text or simple PDF). Provide at least the 4 live FIRs in **both English and Kannada** to demo the translation step.

---

## 3. Target data volumes (the practical anchor)

Sized for a hackathon: enough to look real and exercise every algorithm, small enough to generate and load in minutes.

| Entity | Total | Historical (pre-load) | Live (held back) | Notes |
|---|---|---|---|---|
| **FIRs (cases)** | **65** | 61 | 4 | 1 live FIR per scenario |
| Investigation reports | ~30 | ~26 | 4 | 1 live IR per scenario; ~40% of historical cases get one |
| Persons (total) | ~110 | ~110 | (in live docs) | victims ~65 + offenders/mules/operators ~45 |
| → of which "criminal" persons | ~45 | reused across cases | — | small, deliberately reused pool |
| Accounts | ~140 | ~140 | — | victim ~65 + shared mule/agg/hub/bridge pool ~45 + collection/cash-out ~30 |
| Transactions | ~500 | ~500 | — | rich chains for financial cases, 1–3 for minor cases |
| Devices (IMEI) | ~55 | ~55 | — | controlled pool; some reused across cases |
| Phones | ~95 | ~95 | — | |
| UPI IDs / VPAs | ~75 | ~75 | — | |
| IPs | ~35 | ~35 | — | with geolocation |
| Crypto wallets | ~8 | ~8 | — | USDT cash-out endpoints |
| **Legal: sections** | ~10 | real/curated | — | see Section 10 |
| Legal: elements | ~35 | real/curated | — | 3–5 per section |
| Legal: evidence types | ~15 | real/curated | — | |
| Legal: precedents | ~12 | real/curated | — | real judgments, attributed |
| Reference: districts | 31 | all Karnataka districts | — | |
| Reference: police stations | ~25 | cyber/CEN stations | — | |
| Reference: banks | ~15 | — | — | |

Resulting graph ≈ a few thousand nodes / several thousand edges — highly visualizable, loads fast.

**Crime-type mix across the 65 FIRs** (weight toward what dominates in India, and toward Bengaluru):

| Crime type | Count | Why |
|---|---|---|
| task_scam | ~16 | Scenario 4 surge (15) + background |
| digital_arrest | ~10 | Scenario 1 (4) + Scenario 3 bridge (1) + background |
| investment_scam | ~10 | Scenario 2 live + background |
| upi_fraud | ~10 | Scenario 3 live + background |
| loan_app / otp_fraud / job_scam | ~9 | Scenario 2 history (3) + background |
| sextortion / phishing / mule_account | ~10 | background realism |

**District mix:** Bengaluru-heavy (~40%), then Mysuru, Mangaluru, Hubballi, Belagavi, Dharwad, Tumakuru (all required by scenarios), remainder spread across other Karnataka districts.

**Time span:** historical corpus spread over the **last 12 months**; Scenario 4 surge clustered in the **last 21 days**; Scenario 2 offender history reaches back to **2024** (older dated FIRs). Treat "now" as the demo date.

---

## 4. Entity schemas (fields to generate)

Minimum fields. Add IDs/foreign keys as needed. `*` = used by temporal/spatial analytics — must be populated.

**FIR / Crime**
`fir_id`, `fir_number`, `crime_type`, `date_registered`*, `date_of_offence`*, `district`*, `pincode`*, `lat`*, `long`*, `police_station`, `complainant_person_id`, `accused_person_ids[]`, `amount_involved`, `bns_sections[]`, `it_act_sections[]`, `identifiers_mentioned{phones[],accounts[],upis[],imeis[],ips[],wallets[]}`, `status`, `io_officer`, `narrative_vector_id`, `sub_events[]`* (each `{label, timestamp}`), `is_synthetic=true`.

**Investigation Report**
`report_id`, `fir_id`, `report_date`*, `io_officer`, `findings_vector_id`, `newly_linked_identifiers{...}`, `linked_fir_ids[]`, `seized_items[]`, `arrests[]`, `money_trail_notes`, `suspected_roles[]`.

**Person**
`person_id`, `full_name`, `aliases[]`, `dob`/`age`, `gender`, `address`, `district`*, `education`, `occupation`, `employment_status`, `role` (victim/recruiter/caller/mule/mule_handler/controller), `first_seen_date`*, `linked_case_count`, `kyc_ids{pan,aadhaar_synth}`, `is_synthetic=true`.

**Account**
`account_no`, `bank`, `ifsc`, `branch_district`*, `account_type`, `open_date`*, `kyc_name`, `is_flagged_mule`, `activity_history`* (list of `{timestamp, direction, amount}`).

**Transaction**
`txn_id`, `from_account`, `to_account` (or `to_wallet`), `amount`, `timestamp`* (minute precision), `channel` (UPI/IMPS/NEFT/cash/crypto), `linked_fir_id`.

**Objects:** `Phone{number}`, `Device{imei}`, `UPI{vpa}`, `IP{ip_address, geolocation*}`, `Wallet{address, chain}`.

**Reference:** `District{name, lat, long}`, `PoliceStation{name, district, type}`, `Bank{name}`, `CrimeType{code, label}`.

---

## 5. The shared identifier pool — BUILD THIS FIRST

Create these specific reused identifiers, then wire the scenario cases to them. (Values below are illustrative patterns; generate realistic ones but keep the reuse mapping exact.)

| Pool item | Reused by | Role |
|---|---|---|
| `AGG-ACC-01` (one aggregation account) | Scenario 1 — all 4 cases' trails converge here | the link that joins the digital-arrest ring |
| `CTRL-UPI-01`, `CTRL-IMEI-01` | Scenario 1 — controller, surfaced in the live IR | reveals the ringleader |
| `DEV-IMEI-02`, `UPI-02`, `PHONE-02` | Scenario 2 — the offender across all 4 alias FIRs | entity-resolution join keys |
| `BRIDGE-ACC-03` | Scenario 3 — the Dharwad case AND a historical digital-arrest case | the cross-scam bridge |
| `HUB-ACC-03` | Scenario 3 — busiest node in the layering ring | PageRank target |
| `WALLET-03` | Scenario 3 — crypto cash-out | endpoint |
| `DEV-POOL-04[ ]`, `IP-POOL-04[ ]`, `MULE-SET-04[ ]` | Scenario 4 — shared across the ~15 task-scam cases | forms one community |

**Decoys (must NOT link):**
- A background person who shares a *name* with the Scenario-2 offender but has **no** shared IMEI/UPI/phone → resolution must reject.
- Two background digital-arrest cases with a *similar* MO narrative but **disjoint** identifiers and **no** shared account → similar-case search may surface them, but "find links" must return nothing.

---

## 6. Per-scenario generation specs

For each scenario, generate the historical records (pre-loaded) and the live records (held back). The planted keys come from Section 5.

### 6.1 Scenario 1 — "The Digital Arrest That Wasn't Alone"
- **Historical (pre-load):** 3 digital-arrest FIRs in **Mysuru, Mangaluru, Hubballi**. Each: different victim, phone, beneficiary accounts; **near-identical MO narrative** (TRAI → fake CBI → Skype custody → "RBI verification" transfer). Each case's transaction trail ends by routing into `AGG-ACC-01`. Controller person exists but is **unnamed / weakly linked** (no direct edge yet).
- **Live (held back):** 1 Bengaluru FIR (victim Dr. Anand Rao, ₹42L) whose trail also reaches `AGG-ACC-01`. 1 investigation report supplying `AGG-ACC-01.kyc_name` (mule operator), `CTRL-IMEI-01`, `CTRL-UPI-01` (controller).
- **Temporal:** transfers with minute-level timestamps; the four cases' cash-outs fall in one tight window; some funds left sitting (no outbound after last inbound) = freezable.
- **Spatial:** 4 distinct victim districts; `AGG-ACC-01.branch_district` set so money geography is visible.

### 6.2 Scenario 2 — "Many Names, One Man"
- **Historical (pre-load):** 3 FIRs with the **same offender under alias-variant names** (e.g. "Imraan Sheikh", "I. Shaikh", "Imran Shek"), across **different crime types** (loan_app 2024 → otp_fraud early-2025 Tumakuru → job_scam) and **different districts**, with **escalating `amount_involved`**. All three linked by `DEV-IMEI-02` + `UPI-02` + `PHONE-02`. Seed a faint recruitment cluster (1–2 latent associates/victims).
- **Live (held back):** 1 investment-scam FIR (accused "Imran S.", victim Priya M, ₹15L) carrying `UPI-02`/`PHONE-02`. 1 investigation report with a CDR row whose new phone shares `DEV-IMEI-02`, plus a new account linking 2 more victims.
- **Temporal:** dated crimes 2024 → 2026 with rising amounts (escalation timeline).
- **Spatial:** multi-district operating area (Bengaluru + Tumakuru); optional CDR `cell_tower_district`.

### 6.3 Scenario 3 — "Follow the Money"
- **Historical (pre-load):** 1 Belagavi **digital-arrest** FIR whose money trail touches `BRIDGE-ACC-03`. A broader synthetic mule ledger so a layering structure exists in the graph.
- **Live (held back):** 1 Dharwad **upi_fraud** FIR (victim Sandeep Traders, ₹28L) whose trail also routes through `BRIDGE-ACC-03`. 1 investigation report = a transaction dump for the full layering ring: 1 collection → 3 aggregation → ~11 mule accounts (splits into **sub-₹1-lakh tranches, minutes apart**) → 2 cash-out accounts + `WALLET-03`. `HUB-ACC-03` is the busiest aggregation node; its KYC names the hub operator.
- **Temporal (heavy):** minute-level timestamps showing rapid layering; mule accounts with old `open_date` but dormant-then-burst `activity_history`; freezable funds (~₹6.2L still sitting).
- **Spatial:** accounts across multiple `branch_district`s; victim-vs-beneficiary distance.

### 6.4 Scenario 4 — "The Surge"
- **Historical (pre-load):** ~14 **task_scam** FIRs dated within the **last 21 days**, with **near-duplicate narratives** (Telegram task funnel → fake app → escalating deposits). Their identifiers drawn from `DEV-POOL-04`, `IP-POOL-04`, `MULE-SET-04` so they form **one dense community** (~7 operators). Controller weakly present. Plus unrelated background FIRs across other types/dates so the cluster genuinely stands out.
- **Live (held back):** the 15th task_scam FIR (victim Arjun K, ₹3.5L). 1 investigation report = a seized handler's device dump revealing the operator roster, a script template, and controller accounts.
- **Temporal (heavy):** recent 21-day burst; weekly counts rising sharply vs the prior baseline.
- **Spatial:** `lat`/`long` on the cases for a hotspot heatmap (victims spread across city zones); shared `IP.geolocation` showing operators co-located (one base).

---

## 7. Background / noise data

Generate the remaining ~40 historical FIRs (and their persons/accounts/transactions) as realistic filler so that:
- **Community detection** has noise to separate the Scenario-4 ring from.
- **Trends & hotspots** have volume across districts, crime types and the 12-month window (so SQL aggregations and the heatmap look real).
- **Entity resolution** has non-matching records (including the Section-5 decoys).
- The graph looks populated, not staged.

Background cases must **not** accidentally share the Section-5 pooled identifiers. Give them their own independent identifiers.

---

## 8. Temporal requirements (so time-based analytics run)

- Every `Transaction.timestamp` at **minute precision**.
- Every `Account` has `open_date` + an `activity_history` time series (enables dormant-then-burst).
- Per account, ensure last-inbound vs last-outbound timestamps exist (enables freezable-funds).
- `Crime.date_registered` + `date_of_offence` on every FIR; Scenario-4 cases clustered in the last 21 days; Scenario-2 offender's cases span 2024→2026 with rising amounts.
- FIR `sub_events[]` carry timestamps (enables case-timeline reconstruction).
- Scenario-1 cash-outs fall in one coordinated window.

## 9. Spatial requirements (so location-based analytics run)

- `Crime.district` + `pincode` + `lat`/`long` on every FIR (use real Karnataka district centroids; jitter within district).
- `Account.branch_district` + `ifsc` on every account (enables money geography + victim-beneficiary distance).
- `IP.geolocation` on every IP (enables operator co-location); Scenario-4 operator IPs cluster to one location.
- Ensure the seven scenario districts (Bengaluru, Mysuru, Mangaluru, Hubballi, Belagavi, Dharwad, Tumakuru) are all present.

---

## 10. The legal layer (REAL, curated — do NOT randomize)

Small, hand-curated, real. Where possible fetch real precedent text via the **Indian Kanoon API** and/or the **CC-BY-4.0 Supreme Court judgments dataset**, and **display attribution** ("powered by IKanoon" / CC-BY). Otherwise use the citation + a short summary.

**Sections (~10):** IT Act §66C (identity theft), §66D (cheating by personation using computer resource), §43, §72; BNS §318 (cheating; §318(4) ≈ old IPC 420), §319 (cheating by personation); PMLA §3 (money laundering); BSA §63 (electronic-evidence certificate); plus 1–2 BNSS procedural checkpoints.

**Legal elements (~35, 3–5 per section).** Examples to model:
- §66D → {act of cheating by impersonation; use of computer/communication device; intent to deceive / wrongful gain}.
- BNS §318 → {deception; fraudulent/dishonest inducement; delivery of property or harm; **dishonest intent at inception**}.
- BNS §319 → {pretending to be another; the cheating elements}.
- PMLA §3 → {existence of a predicate/scheduled offence; proceeds of crime; a process/activity connected with the proceeds}.

**Evidence types (~15):** CDR/IPDR, bank/KYC record, UPI transaction log, device forensic image, **§63 BSA certificate**, hash value (SHA-256), WhatsApp/Telegram chat, CCTV, IP/login logs, crypto-wallet trace, seizure memo, screenshot, §79A expert opinion.

**Precedents (~12, real — tag each with outcome + the element it turned on):**
- *Anvar P.V. v. P.K. Basheer* (2014) — §65B is a complete code (established certificate requirement).
- *Arjun Panditrao Khotkar v. Kailash Gorantyal* (2020) — certificate is a condition precedent to admissibility.
- *Randeep Singh @ Rana v. State of Haryana* (2024) — acquittal on missing certificate.
- *State (NCT Delhi) v. Navjot Sandhu* (2005) — **overruled** (tag historical).
- *Shafhi Mohammad v. State of H.P.* (2018) — **overruled** (tag historical).
- *A.M. Mohan v. State* (2023) — dishonest intent at inception for cheating.
- *State v. Manoj Kisku* (2025) — mule-account acquittal; mere credit without conspiracy proof not an offence.
- *Vijay Madanlal Choudhary v. Union of India* — PMLA proceeds/§3 interpretation.

**Legal relationships:**
`(Crime)-[:CHARGED_UNDER]->(Section)`, `(Section)-[:REQUIRES_ELEMENT]->(LegalElement)`, `(LegalElement)-[:SATISFIED_BY]->(EvidenceType)`, `(Case)-[:HAS_EVIDENCE]->(Evidence)-[:SUPPORTS {admissible, has_63_certificate}]->(LegalElement)`, `(Precedent)-[:FAILED_ON]->(LegalElement)`, `(Precedent)-[:INTERPRETS]->(Section)`, `(Section)-[:REPLACES]->(IPCSection)`.

**Plant the checklist gaps:** in the scenario cases, deliberately leave some evidence **without** a §63 certificate (amber), and leave the Scenario-3 cash-out **beneficiary untraced** (the Manoj Kisku risk), so the checklist shows red/amber and matches the relevant precedent.

---

## 11. Generation method per field

| Method | Use for |
|---|---|
| **Faker (Indian locale)** | names, addresses, phone numbers, DOB, occupations, account numbers, IFSC, PAN/Aadhaar-style IDs, district/pincode |
| **LLM** | the free-text **narratives** — FIR stories and investigation-report findings (English; then Kannada for the live FIRs). Same-MO cases must share a near-duplicate template with varied specifics; unrelated cases must read differently |
| **Scripted planting** | every reused identifier, alias cluster, transaction ring topology, time clustering, escalation, community structure, and decoy — i.e. all of Sections 5 & 6. Deterministic and reproducible (seed the RNG) |

---

## 12. Language

- Generate all narratives in **English**.
- Provide **Kannada** versions for the **4 live-demo FIRs** (at least 2 in Kannada as the *source* document) to demonstrate the translate-to-English ingestion step.
- Optionally add Kannada for a small subset of historical FIRs.
- The vector store embeds the **English** text (the pipeline translates first); keep Kannada as a parallel field/file.

---

## 13. Cross-store linking (the platform's key pattern)

- Each graph **Crime/IR node** stores `vector_id` (and the SQL row stores the same).
- Each **vector record** stores `node_id` / `fir_id` + metadata `{district, crime_type, date_registered}`.
- IDs must match exactly across SQL ↔ graph ↔ vector so the agent can hop graph→vector (pull a case's narrative) and vector→graph (pull a similar case's entities).
- Transactions, persons and objects use stable IDs reused across all three stores.

---

## 14. Validation checklist (run after generation, output `validation_report.md`)

**Scenario links fire:**
- [ ] Scn 1: the 4 cases share `AGG-ACC-01`; the live IR connects `CTRL-*` to all four; controller ranks top by centrality.
- [ ] Scn 2: the 4 alias FIRs resolve to one person via `DEV-IMEI-02`/`UPI-02`/`PHONE-02`; amounts escalate by date.
- [ ] Scn 3: `BRIDGE-ACC-03` appears in both a digital-arrest case and the UPI-fraud case; the layering ring resolves; `HUB-ACC-03` is highest-centrality; `WALLET-03` is an endpoint; ~₹6.2L freezable.
- [ ] Scn 4: ~15 task_scam cases in the last 21 days form one community via the shared pools; weekly counts spike; operator IPs co-locate.

**Decoys correctly fail:**
- [ ] The same-name decoy does NOT resolve to the Scn-2 offender.
- [ ] The similar-MO decoy cases surface in similarity search but "find links" returns no shared identifier.

**Temporal/spatial completeness:**
- [ ] 100% of transactions have minute-level timestamps; 100% of accounts have open_date + activity history + branch_district; 100% of FIRs have date + district + pincode + lat/long; 100% of IPs have geolocation.

**Volumes & integrity:**
- [ ] Counts match Section 3 (±10%).
- [ ] No background case accidentally shares a Section-5 pooled identifier.
- [ ] Every graph node `vector_id` resolves to a vector record and back.
- [ ] Legal layer present and attributed; checklist gaps planted (missing §63 certs; untraced beneficiary).

---

## 15. Deliverables recap

1. `/output/historical/{sql,graph,vector,legal}` — the pre-loaded corpus.
2. `/output/live_demo/scenario_{1..4}` — held-back FIR + IR documents (English + Kannada).
3. `/output/manifest/planted_links.md`, `data_dictionary.md`, `validation_report.md`.
4. A reproducible generator (seeded) so the dataset can be regenerated identically.

**Reminder:** all case data is synthetic and must be labelled; statutes and precedents are real and attributed; this dataset is for demonstration only.
