"""Checks for the assistant toolbox.

Focus is the read-only guards. They are a trust boundary: the SQL/Cypher they vet is
written by an LLM from an officer's (or a judge's) free text, and the assistant has
write-capable credentials to all three stores. Everything else here is cheap structural
insurance -- that tools carry the right agent labels and that the money-trail arithmetic
(freezable funds) is right, since a wrong number there is worse than no number.

Needs no database. Run: python backend/tests/test_assistant_tools.py
"""
from __future__ import annotations

import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from app.assistant.tools import (  # noqa: E402
    AGENT_BY_TOOL,
    _fmt_inr,
    _guard_cypher,
    _guard_sql,
    build_tools,
)


class TestSqlGuard(unittest.TestCase):
    def test_allows_plain_reads(self):
        for sql in [
            "SELECT * FROM CaseMaster LIMIT 5",
            "select crimeno from casemaster",
            "WITH x AS (SELECT 1 AS n) SELECT n FROM x",
            "SELECT count(*) FROM CaseMaster;",  # trailing semicolon is fine
        ]:
            self.assertIsNone(_guard_sql(sql), f"should allow: {sql}")

    def test_blocks_writes_and_ddl(self):
        for sql in [
            "DELETE FROM CaseMaster",
            "UPDATE Account SET is_flagged_mule = true",
            "INSERT INTO Account(account_id) VALUES (1)",
            "DROP TABLE CaseMaster",
            "TRUNCATE Account",
            "ALTER TABLE Account ADD COLUMN x int",
            "GRANT ALL ON Account TO PUBLIC",
        ]:
            self.assertIsNotNone(_guard_sql(sql), f"should block: {sql}")

    def test_blocks_stacked_statement_smuggling(self):
        # The classic: a valid SELECT with a write riding behind a semicolon.
        self.assertIsNotNone(_guard_sql("SELECT 1; DROP TABLE CaseMaster"))
        self.assertIsNotNone(_guard_sql("SELECT 1; DELETE FROM Account"))

    def test_blocks_write_disguised_inside_a_read(self):
        # Postgres CTEs can carry writes; the keyword check is what stops these.
        self.assertIsNotNone(_guard_sql("WITH x AS (DELETE FROM Account RETURNING 1) SELECT * FROM x"))
        self.assertIsNotNone(_guard_sql("SELECT pg_sleep(10)"))
        self.assertIsNotNone(_guard_sql("SELECT pg_read_file('/etc/passwd')"))

    def test_blocks_non_select_entrypoints(self):
        for sql in ["", "   ", "EXPLAIN ANALYZE DELETE FROM Account", "CALL something()"]:
            self.assertIsNotNone(_guard_sql(sql))


class TestCypherGuard(unittest.TestCase):
    def test_allows_reads(self):
        for cypher in [
            "MATCH (c:CaseMaster) RETURN c LIMIT 5",
            "match (a:Account)-[r:TRANSACTED_WITH]->(b) return a,b",
            "WITH 1 AS n RETURN n",
            "OPTIONAL MATCH (c:CaseMaster) RETURN c",
        ]:
            self.assertIsNone(_guard_cypher(cypher), f"should allow: {cypher}")

    def test_blocks_writes(self):
        for cypher in [
            "CREATE (n:Evil)",
            "MATCH (n) DETACH DELETE n",
            "MATCH (n) SET n.origin = 'demo'",
            "MERGE (n {entity_uid: 'x'})",
            "MATCH (n) REMOVE n:Account",
            "MATCH (n) DELETE n",
        ]:
            self.assertIsNotNone(_guard_cypher(cypher), f"should block: {cypher}")

    def test_blocks_procedures_and_stacking(self):
        self.assertIsNotNone(_guard_cypher("MATCH (n) CALL { CREATE (:X) } RETURN n"))
        self.assertIsNotNone(_guard_cypher("CALL apoc.periodic.iterate('MATCH (n)','DELETE n',{})"))
        self.assertIsNotNone(_guard_cypher("MATCH (n) RETURN n; CREATE (:X)"))
        self.assertIsNotNone(_guard_cypher("LOAD CSV FROM 'file:///x' AS r RETURN r"))


class TestRegistry(unittest.TestCase):
    def test_every_tool_has_agent_label_and_schema(self):
        tools = build_tools()
        self.assertEqual(len(tools), 12)
        for tool in tools:
            # A step with no agent label can't render under a specialist in the UI.
            self.assertIn(tool.name, AGENT_BY_TOOL, f"{tool.name} has no agent_kind")
            self.assertIn(AGENT_BY_TOOL[tool.name], ("sql", "graph", "vector", "legal"))
            # Descriptions are the routing logic -- an empty one makes a tool invisible.
            self.assertTrue(len(tool.description) > 40, f"{tool.name} description too thin")
            self.assertIsNotNone(tool.args_schema, f"{tool.name} has no args schema")

    def test_tools_expose_async_path(self):
        # The agent runs async; a tool without a coroutine would block the event loop
        # and stall every answer_delta already streaming.
        for tool in build_tools():
            self.assertIsNotNone(tool.coroutine, f"{tool.name} has no async path")

    def test_tool_registry_can_be_filtered_for_specialists(self):
        tools = build_tools(tool_names={"trace_money_flow", "run_cypher_read"})
        self.assertEqual({t.name for t in tools}, {"trace_money_flow", "run_cypher_read"})

    def test_all_four_specialists_are_represented(self):
        kinds = {AGENT_BY_TOOL[t.name] for t in build_tools()}
        self.assertEqual(kinds, {"sql", "graph", "vector", "legal"})


class TestAmountFormatting(unittest.TestCase):
    def test_indian_units(self):
        self.assertEqual(_fmt_inr(4_200_000), "Rs 42.00 lakh")
        self.assertEqual(_fmt_inr(28_00_000), "Rs 28.00 lakh")
        self.assertEqual(_fmt_inr(3_50_00_000), "Rs 3.50 crore")
        self.assertEqual(_fmt_inr(90000), "Rs 90,000")
        self.assertEqual(_fmt_inr(None), "None")


if __name__ == "__main__":
    unittest.main(verbosity=2)
