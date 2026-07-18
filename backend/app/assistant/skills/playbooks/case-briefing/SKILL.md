---
name: case-briefing
agents: case,supervisor
description: "Build a one-case briefing with summary, parties, charges, evidence and timeline. Use when the officer asks to summarise this case, lay out the timeline, explain the FIR, brief the case, or say what happened in the selected CrimeNo."
---

# Case Briefing

Follow this workflow exactly.

1. Call `get_case_summary` with `case_ref=""` unless the officer supplied another CrimeNo.
2. Use the returned case facts only. Do not add suspects, amounts, sections or dates that were not returned.
3. If a timeline table artifact was emitted, mention the main sequence in the answer instead of restating every row.
4. Lead with a short case card:
   - CrimeNo and case_id
   - offence type
   - district/station
   - victim/complainant
   - loss amount if returned
5. Then give a compact timeline in order.
6. End with immediate next leads if the tool output clearly supports them, otherwise say what evidence is missing.

UI expectations:
- Timeline table artifact appears when sub-events exist.
- FIR citation opens the case narrative document artifact.
- Answer must be finding-first, not tool-first.
