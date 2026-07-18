---
name: operator-org-chart
agents: network,supervisor
description: "Build the operator org chart / role map for a seized-device ring: each operator, their role (caller / mule_handler / recruiter / controller), and the device or UPI they use. Use when the officer asks to build the org chart, role map, operator roster, who does what, the structure or hierarchy of a ring or gang, or to map operators from seized device data."
---

# Operator Org Chart

A seized handler device reveals the ring's operators as role-typed Person nodes. Follow this
workflow exactly and STOP as soon as you have the roster — do not loop over exploratory queries.

1. Get the whole org chart with ONE `run_cypher_read` call:

   MATCH (op:Accused) WHERE op.role IS NOT NULL
   OPTIONAL MATCH (op)-[:OWNS]->(o)
   RETURN op.display_name AS operator, op.role AS role, collect(o.display_name) AS uses
   ORDER BY op.role

2. If it returns no rows, the roster has not been ingested from the device dump yet — say so
   plainly and stop. Never invent operator names or roles.

3. Present the org chart from the rows returned:
   - Lead with the **controller** (role = controller) — the person all commission payouts route to.
   - Then group the rest by role: recruiter(s), caller(s), mule_handler(s).
   - For each operator, name the device IMEI / UPI they use (the `uses` list).

4. Optionally call `detect_community` once to state how many cases the ring's shared devices touch
   (its scale), then stop.

5. Caveat: roles are read from seized-device evidence — this is an investigative lead for tasking
   stations, not proof of membership.

Do NOT run many variations of the query. The single Cypher above IS the org chart; answer once you
have it.

UI expectations:
- A table of operator | role | device/UPI, controller first.
- The answer names the controller and each operator's role.
