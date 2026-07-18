---
name: money-trail-analysis
agents: financial,supervisor
description: "Trace fraud money movement and produce a golden-hour money-trail finding. Use when the officer asks where the money went, how fast it moved, what can be frozen, layering, mule accounts, crypto cash-out, or dormant-then-burst laundering."
---

# Money Trail Analysis

Follow this workflow exactly.

1. Call `trace_money_flow`.
   - If the officer named an account, pass `account_number`.
   - Otherwise pass `case_ref=""` for the current case.
2. Read the returned summary for:
   - total transfers and total amount
   - first and last timestamp / elapsed minutes
   - freezable funds
   - crypto wallet or cash-out endpoint
3. If the trail is empty, answer that no outbound transfers are recorded and name the missing data needed.
4. If freezable funds exist, lead with them before anything else.
5. Then describe the trail in time order and call out rapid layering if money moved within minutes.
6. Treat mule/cash-out labels as investigative leads, not proof.

UI expectations:
- Money-flow graph artifact.
- Transfers table artifact ordered by timestamp.
- Answer names the freezable account(s), amount, and last inbound time when available.
