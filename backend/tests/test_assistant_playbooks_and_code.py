from __future__ import annotations

import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from app.assistant.skills import analysis  # noqa: E402
from app.assistant.skills.playbooks import build_playbook_tools, load_playbooks  # noqa: E402
from app.assistant.graph import _heuristic_plan, build_assistant_graph  # noqa: E402
from app.assistant.specialists import SPECS, _bounded_history, build_specialist_subgraph  # noqa: E402
from langchain_core.messages import AIMessage, HumanMessage  # noqa: E402


class TestPlaybooks(unittest.TestCase):
    def test_scenario_playbooks_are_discoverable_by_description(self):
        playbooks = {p.name: p for p in load_playbooks()}
        self.assertIn("find-links-after-similarity", playbooks)
        self.assertIn("money-trail-analysis", playbooks)
        self.assertIn("prosecution-readiness", playbooks)
        self.assertIn("find links", playbooks["find-links-after-similarity"].description.lower())
        self.assertIn("where the money went", playbooks["money-trail-analysis"].description.lower())

    def test_agent_filtering_keeps_relevant_skills(self):
        network_tools = {t.name for t in build_playbook_tools("network")}
        self.assertIn("skill_find_links_after_similarity", network_tools)
        self.assertIn("skill_offender_profile", network_tools)
        self.assertNotIn("skill_case_briefing", network_tools)


class TestPythonTool(unittest.TestCase):
    def test_python_tool_captures_stdout_and_generated_artifact(self):
        saved = {"artifacts": [], "blobs": []}
        old_save_artifact = analysis.persistence.save_artifact
        old_save_blob = analysis.persistence.save_blob
        try:
            analysis.persistence.save_artifact = lambda artifact, session_id, run_id, stratus_key=None: saved["artifacts"].append(artifact)  # type: ignore[assignment]
            analysis.persistence.save_blob = lambda artifact_id, blob: saved["blobs"].append((artifact_id, blob))  # type: ignore[assignment]
            tool = analysis.build_python_tool("sess-test", "run-test")
            result = tool.invoke({
                "code": "from pathlib import Path\nPath('out.txt').write_text('artifact ok')\nprint('hello')",
                "purpose": "unit test",
            })
        finally:
            analysis.persistence.save_artifact = old_save_artifact  # type: ignore[assignment]
            analysis.persistence.save_blob = old_save_blob  # type: ignore[assignment]

        self.assertIn("Python exited 0", result)
        self.assertIn("hello", result)
        self.assertEqual(len(saved["artifacts"]), 1)
        self.assertEqual(saved["artifacts"][0].format, "text")
        self.assertEqual(saved["blobs"][0][1], b"artifact ok")


class TestSupervisorGraph(unittest.TestCase):
    def test_graph_has_supervisor_specialist_and_synthesize_nodes(self):
        graph = build_assistant_graph(language="en", case_context=None, memories=[])
        node_ids = set(graph.get_graph().nodes.keys())
        for key in ("supervisor", "synthesize", "case", "financial", "network", "mo", "legal"):
            self.assertIn(key, node_ids)

    def test_specialist_state_channel_has_fan_in_reducer(self):
        # The fan-in accumulator MUST carry a reducer, or parallel specialists clobber
        # each other. operator.add is what makes map-reduce safe here. (graph_state uses
        # `from __future__ import annotations`, so resolve the string hints with extras.)
        import operator
        from typing import get_type_hints
        from app.assistant.graph_state import AssistantState
        hints = get_type_hints(AssistantState, include_extras=True)["specialist_results"]
        self.assertIn(operator.add, getattr(hints, "__metadata__", ()))

    def test_heuristic_router_is_a_safe_net(self):
        self.assertEqual(_heuristic_plan("where did the money go, how fast?", None)[0]["key"], "financial")
        self.assertEqual(_heuristic_plan("has this MO appeared elsewhere?", None)[0]["key"], "mo")
        self.assertEqual(_heuristic_plan("is this prosecutable, what's missing?", None)[0]["key"], "legal")
        # Empty question with a case in context defaults to the case briefing specialist.
        self.assertEqual(_heuristic_plan("", {"crime_no": "X"})[0]["key"], "case")

    def test_each_specialist_is_a_compiled_react_subgraph(self):
        for spec in SPECS:
            sub = build_specialist_subgraph(spec, language="en", case_context=None, memories=None)
            ids = set(sub.get_graph().nodes.keys())
            self.assertIn("reason", ids)
            self.assertIn("tools", ids)

    def test_bounded_history_keeps_recent_turns_and_truncates(self):
        # This is what makes a specialist stateful across turns: it must carry the last few
        # messages (not all of them) and never let one huge answer blow up its context.
        convo = [
            HumanMessage(content="turn 1"), AIMessage(content="ans 1"),
            HumanMessage(content="turn 2"), AIMessage(content="ans 2"),
            HumanMessage(content="turn 3"), AIMessage(content="x" * 5000),
        ]
        trimmed = _bounded_history(convo, turns=4, max_chars=100)
        self.assertEqual(len(trimmed), 4)                      # only the last 4
        self.assertEqual(trimmed[0].content, "turn 2")         # oldest kept, in order
        self.assertIsInstance(trimmed[-1], AIMessage)          # message class preserved
        self.assertTrue(trimmed[-1].content.endswith("..."))   # long answer clipped
        self.assertLessEqual(len(trimmed[-1].content), 104)
        self.assertEqual(_bounded_history([]), [])             # no history -> nothing


if __name__ == "__main__":
    unittest.main(verbosity=2)
