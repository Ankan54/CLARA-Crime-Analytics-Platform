---
name: find-links-after-similarity
agents: network,mo,supervisor
description: "Find structural links among cases after a similar-cases or same-modus-operandi result. Use when the officer clicks or asks find links among these cases, whether similar cases are connected, whether separate investigations share an account, device, UPI, phone or IP, or when vector results must be checked in the graph."
---

# Find Links After Similarity

Follow this workflow exactly.

1. If the officer has not supplied case refs yet, call `find_similar_cases` first.
   - Use `case_ref=""` for the current case.
   - Extract the CrimeNos from the returned "Case refs for link analysis" line.
2. Call `find_links_between_cases` with every CrimeNo from step 1 plus the current case when available.
3. If shared identifiers are found:
   - lead with the strongest shared object, usually the one shared by most cases
   - name its type and display value
   - list the linked CrimeNos and districts when returned
4. If no shared identifier is found, say the MO similarity has no structural identifier link in current data.
5. Do not claim one gang unless the graph returned shared infrastructure.

UI expectations:
- Similar-cases table when step 1 ran.
- Shared-identifier graph artifact after `find_links_between_cases`.
- The answer must explain the vector-to-graph chain in plain language.
