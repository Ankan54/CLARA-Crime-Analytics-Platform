# KSP Crime Intelligence — UI/UX Design Direction

Working name: **AIKYA** (ಐಕ್ಯ — Kannada for "unity"), because the product's core value is
*connecting cases* — shared accounts, shared devices, shared people. Placeholder; rename freely.

## 1. Who uses this

| Persona | Goal | Implication |
|---|---|---|
| Investigating Officer (IO) | Upload case documents, review what the system found, approve | Plain language, zero jargon. The backend already speaks "officer" (`stage_labels.py`) — the UI must too. |
| Reviewing Officer | Resolve "is this the same person?" matches | Side-by-side comparison, one decision at a time, green/red signal from `match_score`. |
| System Admin (SP/tech cell) | Tune match threshold, manage extraction schemas | Dense, technical is fine here. Guard rails on destructive actions. |
| Datathon judges | Understand the product in 90 seconds | Landing page = pitch. Show the pipeline, the graph, the money trail. |

## 2. Design principles

1. **Case-file language, not pipeline language.** "Reading the document", not `EXTRACTING_TEXT`.
   The backend sends both — always render the label, log the code.
2. **The review gate is the hero.** Nothing enters the databases without an officer's
   *Proceed*. Every screen reinforces that the human is in command.
3. **Evidence-grade legibility.** Crime numbers, IMEIs, account numbers, amounts are always
   monospace + tabular figures. They get copied into reports; they must never be ambiguous.
4. **Dense but calm.** Officers scan tables all day. 8px rhythm, 36px table rows,
   one accent colour, whitespace does the grouping.
5. **Never dead-end on failure.** Uploads partially fail per file; runs fail per stage.
   Every error state carries the human-readable message from the API and a retry path.

## 3. Theme — "The Case Desk"

Institutional authority without sterile corporate grey. A digital case file: warm paper
surfaces, deep police-navy ink, one gold accent drawn from Karnataka (Mysore gold).
Light-first (bright station offices, long table-reading sessions); the dark ink surface is
reserved for the app header/hero, which gives the command-center gravitas without an
all-dark UI.

### Colour tokens (see `tokens.css`)

| Token | Value | Use |
|---|---|---|
| `--ink` | `#0C1B33` | Primary. Nav, hero, primary buttons, headings |
| `--ink-2` | `#16294A` | Raised dark surfaces |
| `--paper` | `#F6F4EE` | App background (warm paper) |
| `--surface` | `#FFFFFF` | Cards, tables |
| `--gold` | `#C9A227` | Accent: active states, highlights, hero details |
| `--text` | `#1B2437` | Body text on light (≥ 4.5:1 everywhere) |
| `--text-dim` | `#5B6477` | Secondary text |
| `--ok` | `#1A7F4B` | Success / "merge suggested" (green matches) |
| `--warn` | `#B45309` | Warnings, REVIEW_PENDING accents |
| `--danger` | `#B3261E` | Failures, destructive, "red" matches |
| `--info` | `#1D4ED8` | Links, info chips |

Functional colours always pair with an icon or text — never colour alone (WCAG).

### Typography

| Role | Font | Notes |
|---|---|---|
| Display / headings | **Archivo** (600–800) | Authoritative grotesque, tightens well at display sizes |
| Body / UI | **Public Sans** (400/500/600) | Designed for government digital services; 16px base, 1.55 line-height |
| Data / IDs | **IBM Plex Mono** (400/500) | Crime numbers, run IDs, IMEIs, amounts; `font-variant-numeric: tabular-nums` |

### Texture & motion

- Hero/dark surfaces carry a faint **fingerprint-contour SVG** motif — on-theme, memorable,
  never behind body text.
- Motion budget: 150–300ms ease-out micro-interactions, staggered card reveals on the
  landing page only. Live pipeline rows pulse subtly while `RUNNING`. All motion behind
  `prefers-reduced-motion`.

## 4. Screen map (against the real API)

| # | Screen | Backing endpoints |
|---|---|---|
| 1 | Landing / pitch | — |
| 2 | **Ingest** (upload wizard → live pipeline → review handoff) | `POST /upload`, `POST /process/{batch}`, `WS /ws/pipeline/{run}`, `GET /runs` |
| 3 | Review findings (centrepiece, next iteration) | `GET /process/{run}/findings`, `POST /review-queue/{id}/resolve`, `POST /process/{run}/proceed` |
| 4 | Cases list + detail | `GET /cases`, `GET /cases/{id}` |
| 5 | **Admin** (threshold + schema versions) | `/admin/config/entity-review-threshold`, `/admin/schema*` |

Samples built in this folder: `landing.html`, `ingest.html`, `admin.html`.
All three share `tokens.css`. Open directly in a browser — no build step.

### Ingest page states (all designed into the sample)

1. **Compose batch** — dropzone; per-file type tag (FIR / IR / Evidence); rule callouts
   ("a new case must begin with an FIR", 10 files / 60 MB / 15 MB per file); per-file
   validation errors inline (partial-success model).
2. **Live pipeline** — stepper `Upload → Extract → Review → Load`; per-file rows showing
   the officer-friendly `stage_label`; run id in mono; WebSocket-driven.
3. **Ready for review** — amber banner with findings counts and the single primary CTA
   *Review findings*. Phase B only ever starts from the review screen's *Proceed*.
4. **Failure** — stage + message from `error_stage`/`error_message`, *Retry* button
   (`POST /process/{run}/retry`).

### Admin page sections

1. **Entity match threshold** — slider 0.50–0.99 mapped to `PUT /admin/config/entity-review-threshold`;
   explains the green/red consequence on review items; shows current auto-merge behaviour.
2. **Extraction schemas** — 5 doc types; version list with Active badge; activate/rollback
   with confirmation; field table (group, field, type, required, identifier, hint);
   relationship list (`INVOLVES`, `OWNS`, `TRANSACTED_WITH`…). New versions start inactive.

## 5. Component inventory (for the eventual build)

Badges (status/phase/file-type), stepper, dropzone, file row, stage-progress row,
entity chips (person/account/UPI/phone/device), match card (side-by-side, green/red),
money-trail table, graph preview panel, threshold slider, version table, field grid,
confirm dialog, toast. Recommended stack when building for real: React + Tailwind with
these tokens as CSS variables (shadcn/ui compatible).

## 6. Anti-patterns we are explicitly avoiding

- Purple-gradient SaaS look, emoji icons, placeholder-only form labels.
- Raw pipeline codes in officer-facing copy.
- Modal-heavy flows: review is a full page, not a popup.
- Colour-only signalling on match cards (score + reasons always in text).
