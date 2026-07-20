---
name: find-links-after-similarity
agents: network,supervisor
description: "Find structural links among cases after a similar-cases or same-modus-operandi result. Use ONLY when the officer explicitly asks to find links / whether cases are connected / whether they share an account, device, UPI, phone or IP. This is the SEPARATE follow-up step AFTER a similar-cases answer -- do NOT run it as part of answering 'find similar cases / same MO' (that answer stops at the narrative similarity)."
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
