---
name: prosecution-readiness
agents: legal,supervisor
description: "Assess whether a cyber or financial crime case is prosecution-ready using legal elements, evidence gaps and precedents. Use when the officer asks is this prosecutable, what must I prove, what's missing, weak point, BSA 63 certificate, admissibility, PMLA, predicate offence, or precedent risk."
---

# Prosecution Readiness

Follow this workflow exactly.

1. Call `legal_checklist` with `case_ref=""` unless the officer supplied another case.
2. Extract:
   - green / amber / red counts
   - amber items caused by BSA section 63 certificate gaps
   - missing elements
   - precedents returned by the tool
3. If the officer asks for a specific section or missing element, call `find_precedents` for only that section/element.
4. Lead with the practical filing risk:
   - "mostly ready" only if reds are zero
   - "not ready" if key elements are red
   - "fix admissibility before filing" when electronic evidence is amber due to missing certificate
5. Cite only precedents returned by tools. Do not invent legal cases.
6. Always end with decision-support wording: verify section mappings with counsel.

UI expectations:
- Legal checklist table.
- Precedent citations for flagged elements only.
- Answer clearly separates missing evidence from inadmissible evidence.
