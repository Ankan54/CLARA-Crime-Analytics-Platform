---
name: laundering-velocity
agents: financial,supervisor
description: "Measure how fast money moved through the chain after a fraud: time between first inbound and last outbound per hop, total elapsed minutes, and whether the speed indicates pre-arranged mule coordination. Use when the officer asks about laundering speed, layering time, how fast the money moved, golden hour, or rapid-fire transfers."
---

# Laundering Velocity Analysis

This skill uses generic SQL queries only — no hardened tools. It demonstrates that a new
markdown file = a new analytical capability with zero code change.

## Steps

1. Find the seed accounts for the case using `run_sql_select`:
   ```sql
   SELECT a.id, a.account_number_normalized, a.bank_name
   FROM Account a
   JOIN (SELECT DISTINCT entity_uid FROM (
       SELECT unnest(string_to_array(regexp_replace(properties::text, '[{}"]', '', 'g'), ',')) AS entity_uid
       FROM -- fallback: use the simple linked_case_id join
   )) x ON false
   WHERE a.linked_case_id = :case_id
   ```
   Simplified: run `SELECT id, account_number_normalized, bank_name FROM Account WHERE linked_case_id = :case_id`
   replacing `:case_id` with the case_id in context.

2. Get all transactions involving those accounts:
   ```sql
   SELECT t.from_account_id, t.to_account_id, t.amount, t.currency, t.timestamp, t.channel,
          fa.account_number_normalized AS from_acct, ta.account_number_normalized AS to_acct
   FROM Transaction t
   JOIN Account fa ON fa.id = t.from_account_id
   JOIN Account ta ON ta.id = t.to_account_id
   WHERE t.from_account_id IN (:seed_ids) OR t.to_account_id IN (:seed_ids)
   ORDER BY t.timestamp
   ```

3. Compute velocity metrics from the results:
   - First transfer timestamp, last transfer timestamp, total elapsed minutes.
   - Per-hop time: time between consecutive transfers through the chain.
   - Flag rapid layering: any hop < 5 minutes suggests pre-arranged mule coordination.

4. Report to the officer:
   - Total amount moved, number of hops, elapsed time.
   - Whether the velocity suggests automated/coordinated laundering or manual cash-out.
   - Which accounts moved money fastest (the likely mule layer).

UI expectations:
- Table artifact of transfers ordered by timestamp with per-hop elapsed time.
- Headline: total elapsed time + whether it's within the golden hour (< 60 min).
