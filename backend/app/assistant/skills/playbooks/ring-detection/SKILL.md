---
name: ring-detection
agents: network,mo,supervisor
description: "Determine whether a surge or group of cases is one organised ring rather than copycats. Use for organised ring, gang, community, cluster, lead operator, shared infrastructure, centrality, hotspot, where is it concentrated, or is this surge organised."
---

# Ring Detection

Follow this workflow exactly.

1. Call `detect_community`.
   - If case refs are given, pass them.
   - If the officer asks about a recent surge, pass `crime_type` and `days` when stated.
2. Read the largest cluster size, number of clusters, and central shared objects.
3. If the officer asks where it is concentrated, call `query_case_stats` with `group_by="district"` and the same crime-type/date filters.
4. Lead with the verdict:
   - "consistent with one operation" only if shared infrastructure connects multiple cases
   - "looks like copycats/independent" if no infrastructure is shared
5. Then name the central device/account/UPI/IP and the cases it touches.
6. Keep the caveat: this is an investigative lead, not proof of membership.

UI expectations:
- Most-connected shared objects table.
- District/hotspot table when location is requested.
- Answer highlights central operator/object and spread.
