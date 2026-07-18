---
name: surge-check
agents: mo,supervisor
description: "Detect an emerging crime pattern or spike from narrative similarity plus case counts. Use when the officer asks if this is part of a known pattern, emerging pattern, surge, spike, recent wave, same script in the last days, or how many similar cases appeared recently."
---

# Surge Check

Follow this workflow exactly.

1. Call `find_similar_cases`.
   - Use `case_ref=""` when a case is selected.
   - Use `text_query` if the officer describes an MO without a selected case.
2. Extract the similar CrimeNos, scores, crime types and districts.
3. Call `query_case_stats` with:
   - `group_by="month"` for trend over time, or `group_by="district"` for hotspot
   - crime type filter when the similar cases share one
   - date window if the officer stated one
4. Frame the result as "Emerging Pattern" only when the similar set and count trend support it.
5. Include score bands: above 0.85 is strong MO similarity; lower scores are possible matches.

UI expectations:
- Similar-cases table with scores.
- Trend or district table artifact.
- Follow-up action to find links among the similar cases.
