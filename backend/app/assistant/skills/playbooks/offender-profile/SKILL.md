---
name: offender-profile
agents: network,supervisor
description: "Build an alias-resolution and repeat-offender profile. Use when the officer asks do we know this accused, are these names the same person, show his history, escalation, aliases, shared IMEI, shared UPI, shared phone, or operating area."
---

# Offender Profile

Follow this workflow exactly. `person_history` is the RIGHT tool here — it collapses aliases via
shared device/UPI/phone. Do NOT hand-write Cypher to resolve aliases; that is what this tool does.

0. Get the accused NAME if you only have a case (person_history needs a name, not a case_id):
   run_cypher_read: `MATCH (c:CaseMaster {case_id: <case_id>})<-[:INVOLVES]-(a:Accused) RETURN a.display_name`
   (match on case_id INTEGER or display_name = crime_no, never entity_uid).
1. Call `person_history` with that name (or the name/alias the officer supplied).
2. From the returned result, extract:
   - aliases / recorded names
   - shared identifiers proving the link
   - linked cases in date order
3. If the officer asks for escalation, call `run_sql_select` for those case ids or CrimeNos to order by date and amount.
4. If districts are present, describe the operating area.
5. Use a transparent risk read only:
   - linked-case count
   - recency
   - total or rising loss amounts when returned
   - role if returned
   Never output an opaque score.
6. State clearly that alias resolution is an evidence-backed lead for officer review.

UI expectations:
- Case-history table artifact.
- Answer names the shared device/UPI/phone evidence, not just fuzzy name similarity.
