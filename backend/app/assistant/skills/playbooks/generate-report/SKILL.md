---
name: generate-report
agents: case,financial,legal,supervisor
description: "Produce a polished downloadable PDF by first composing HTML, then converting it. Use when the officer asks to generate a report, make a PDF, export this, prepare a dossier, case brief document, give me a summary I can download/print/share, or put this analysis in a report. Not for ordinary on-screen answers."
---

# Generate Report (HTML first, then PDF)

You have `generate_report` (deterministic HTML→PDF renderer) plus `run_python`,
`list_files`, `read_file`, `read_artifact`, and the artifacts already produced this turn.
Neither WeasyPrint nor xhtml2pdf runs JavaScript, so **embed charts as static PNG images**
(matplotlib), not Plotly HTML. Interactive Plotly charts stay on-screen; the PDF gets the
matching PNG.

## Flow

1. **Inventory what you already have.** Call `list_files`. Note artifact ids/titles for
   tables, money trails, and any PNG charts. Use `read_artifact` / `read_file` if you need
   numbers back.

2. **Fill gaps.** If a needed chart is missing or only exists as interactive HTML, run
   `run_python` with matplotlib and save a PNG named with spaces
   (e.g. `Cases by District.png`). Gather any missing facts with the normal SQL/graph/legal
   tools BEFORE composing the report.

3. **Choose the document type** from the officer's ask (recipes below) and compose
   `sections: [{heading, body_markdown}, ...]`. Keep every identifier, amount, date and
   legal citation exactly as the tools returned. Leave `include_artifacts=True` so this
   run's tables/graph trails attach automatically — do not retype those numbers.

4. **Call `generate_report` once** with a short specific title
   (e.g. `Case C129…0042 — Investigation Brief`).

5. **Answer in one or two lines** that the PDF is ready and attached. Do NOT paste the
   full report body into chat.

## Document-type recipes

### A. Session analysis summary
When: "summarise this analysis", "PDF of what we just found", "export this conversation".
Sections:
- **What was asked** — the officer's question(s) in this session, one sentence each.
- **Key findings** — 4–8 bullets, most actionable first.
- **Supporting numbers** — short markdown tables or references to attached table artifacts.
- **Visuals** — mention which chart PNGs were generated; they attach via include_artifacts
  when present as document artifacts. If only HTML charts exist, regenerate PNGs in step 2.
- **Sources** — CrimeNos, document titles, and citation labels from the inventory.
- **Recommended next steps** — concrete officer actions.

### B. Case dossier / investigation brief
When: "case brief", "dossier", "case summary PDF", a CrimeNo is in context.
Sections: Summary; Parties (accused/victim/complainant); Timeline; Money trail;
Network & links; Legal position; Evidence on file; Recommended next steps.

### C. Money-trail report
When: "money trail report", "freeze report", "laundering summary PDF".
Sections: Headline freezable funds; Trail hops with amounts/timestamps; Velocity /
layering notes; Cash-out point; Accounts to freeze; PMLA / predicate notes if available.

### D. Legal / prosecution readiness
When: "prosecution report", "what's missing for charge", "BSA 63 gap report".
Sections: Charges; Elements proven vs missing; Evidence gaps (§63/BSA); Precedents;
Recommended collection steps.

## HTML polish (what `generate_report` already does for you)
The tool wraps your sections in a print-ready template (header, meta, officer name,
Indic-capable font). You supply clear headings and markdown bodies with tables/lists.
Do not invent CSS or full HTML documents yourself unless a future tool asks for raw HTML
— pass structured sections.

## Hard rules
- Call `generate_report` only when a document is explicitly requested.
- Build from tool output and session artifacts only; invent nothing.
- Charts inside PDFs must be static PNG/SVG (matplotlib), not Plotly HTML.
- File/artifact titles use spaces, not underscores.
- One report per request.

## UI expectations
- A PDF artifact appears in the trail and opens in the artifact drawer.
