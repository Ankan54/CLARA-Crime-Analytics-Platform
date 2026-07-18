from __future__ import annotations

import asyncio
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

    def test_matplotlib_chart_is_collected_as_a_png_artifact(self):
        # The whole point of the chart fix: agent-written matplotlib code must run in the
        # venv and surface a real PNG artifact (not a text bar chart). If matplotlib isn't
        # installed or the Agg backend isn't picked up, this fails loudly.
        saved = {"artifacts": [], "blobs": []}
        old_save_artifact = analysis.persistence.save_artifact
        old_save_blob = analysis.persistence.save_blob
        try:
            analysis.persistence.save_artifact = lambda artifact, session_id, run_id, stratus_key=None: saved["artifacts"].append(artifact)  # type: ignore[assignment]
            analysis.persistence.save_blob = lambda artifact_id, blob: saved["blobs"].append((artifact_id, blob))  # type: ignore[assignment]
            tool = analysis.build_python_tool("sess-test", "run-mpl")
            result = tool.invoke({
                "code": (
                    "import matplotlib\n"
                    "matplotlib.use('Agg')\n"
                    "import matplotlib.pyplot as plt\n"
                    "fig, ax = plt.subplots()\n"
                    "ax.barh(['Bengaluru Urban', 'Kodagu'], [13, 5])\n"
                    "fig.savefig('case_count_by_district.png')\n"
                    "print('chart done')\n"
                ),
                "purpose": "district chart",
            })
        finally:
            analysis.persistence.save_artifact = old_save_artifact  # type: ignore[assignment]
            analysis.persistence.save_blob = old_save_blob  # type: ignore[assignment]
            analysis.cleanup_run_workspace("run-mpl")

        self.assertIn("Python exited 0", result)
        self.assertEqual(len(saved["artifacts"]), 1)
        self.assertEqual(saved["artifacts"][0].format, "png")
        self.assertEqual(saved["artifacts"][0].title, "case count by district")
        self.assertTrue(saved["blobs"][0][1].startswith(b"\x89PNG"))  # real PNG magic bytes

    def test_plotly_interactive_html_is_collected(self):
        saved = {"artifacts": [], "blobs": []}
        old_save_artifact = analysis.persistence.save_artifact
        old_save_blob = analysis.persistence.save_blob
        try:
            analysis.persistence.save_artifact = lambda artifact, session_id, run_id, stratus_key=None: saved["artifacts"].append(artifact)  # type: ignore[assignment]
            analysis.persistence.save_blob = lambda artifact_id, blob: saved["blobs"].append((artifact_id, blob))  # type: ignore[assignment]
            tool = analysis.build_python_tool("sess-test", "run-plotly")
            result = tool.invoke({
                "code": (
                    "import plotly.graph_objects as go\n"
                    "fig = go.Figure(go.Bar(x=[13, 6], y=['Bengaluru Urban', 'Kodagu'], orientation='h'))\n"
                    "fig.write_html('Cases by District.html', include_plotlyjs=True, full_html=True)\n"
                    "print('plotly ok')\n"
                ),
                "purpose": "interactive chart",
            })
        finally:
            analysis.persistence.save_artifact = old_save_artifact  # type: ignore[assignment]
            analysis.persistence.save_blob = old_save_blob  # type: ignore[assignment]
            analysis.cleanup_run_workspace("run-plotly")

        self.assertIn("Python exited 0", result)
        self.assertEqual(len(saved["artifacts"]), 1)
        self.assertEqual(saved["artifacts"][0].format, "html")
        self.assertEqual(saved["artifacts"][0].title, "Cases by District")
        html = saved["blobs"][0][1].decode("utf-8", errors="replace")
        self.assertIn("plotly", html.lower())

    def test_visualisation_and_report_skills_are_discoverable(self):
        by_name = {p.name: p for p in load_playbooks()}
        self.assertIn("visualize-data", by_name)
        self.assertIn("generate-report", by_name)
        self.assertIn("chart", by_name["visualize-data"].description.lower())
        self.assertIn("pdf", by_name["generate-report"].description.lower())
        for agent in ("case", "financial", "network", "mo"):
            names = {p.name for p in load_playbooks(agent)}
            self.assertIn("visualize-data", names)

    def test_display_title_replaces_underscores(self):
        self.assertEqual(analysis.display_title_from_filename("Cases_by_District.html"), "Cases by District")
        self.assertEqual(analysis.display_title_from_filename("Money Trail.png"), "Money Trail")


class TestSupervisorGraph(unittest.TestCase):
    def test_graph_has_supervisor_specialist_synthesize_and_respond_nodes(self):
        graph = build_assistant_graph(language="en", case_context=None, memories=[])
        node_ids = set(graph.get_graph().nodes.keys())
        for key in ("supervisor", "synthesize", "respond", "case", "financial", "network", "mo", "legal"):
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


class TestGuardrailRouting(unittest.TestCase):
    def test_route_to_respond_when_direct_answer_set(self):
        graph = build_assistant_graph(language="en", case_context=None, memories=[])
        node_ids = set(graph.get_graph().nodes.keys())
        self.assertIn("respond", node_ids)

    def test_route_to_specialists_when_no_direct_answer(self):
        plan = _heuristic_plan("trace the money trail for case X", None)
        self.assertTrue(len(plan) > 0)
        self.assertTrue(all(p["key"] != "respond" for p in plan))

    def test_identity_streams_greeting_through_respond_not_fallback(self):
        # Regression: Send's payload REPLACES the respond node's state, so direct_answer must
        # ride in the Send payload. If it doesn't, respond streams "" and the run falls through
        # to the generic "could not produce an answer" fallback for a simple "hi".
        import app.assistant.graph as graphmod
        from app.assistant.graph import _RoutingPlan

        greeting = "Hello! I'm CLARA, your crime analytics assistant. How can I help you today?"

        class _FakePlanner:
            def with_fallbacks(self, _):
                return self

            async def ainvoke(self, _messages):
                return _RoutingPlan(mode="identity", direct_answer=greeting, assignments=[])

        class _FakeLLM:
            def with_structured_output(self, _cls):
                return _FakePlanner()

            def with_fallbacks(self, _):
                return self

        orig = graphmod.build_llm_pair
        graphmod.build_llm_pair = lambda purpose: (_FakeLLM(), _FakeLLM())
        try:
            graph = build_assistant_graph(language="en", case_context=None, memories=[])
            state = asyncio.run(graph.ainvoke({"question": "hi"}, config={"recursion_limit": 10}))
        finally:
            graphmod.build_llm_pair = orig

        self.assertEqual(state.get("final_answer"), greeting)
        self.assertNotIn("could not produce an answer", state.get("final_answer", ""))


class TestFriendlyTitles(unittest.TestCase):
    def test_every_spec_has_friendly_action(self):
        for spec in SPECS:
            self.assertTrue(spec.friendly_action, f"{spec.key} missing friendly_action")

    def test_friendly_tool_titles_cover_main_tools(self):
        from app.assistant.tools import FRIENDLY_TOOL_TITLES
        expected = {"trace_money_flow", "run_sql_select", "run_cypher_read",
                    "find_similar_cases", "legal_checklist", "get_case_summary"}
        for tool in expected:
            self.assertIn(tool, FRIENDLY_TOOL_TITLES)


class TestPersonaAndRefusal(unittest.TestCase):
    def test_system_prompt_contains_clara_and_no_internals(self):
        from app.assistant.agent import SYSTEM_PROMPT
        self.assertIn("CLARA", SYSTEM_PROMPT)
        self.assertIn("Crime Lifecycle Analytics and Reasoning Assistant", SYSTEM_PROMPT)
        self.assertIn("NEVER mention", SYSTEM_PROMPT)

    def test_planner_prompt_contains_persona_and_scope(self):
        from app.assistant.graph import _PLANNER_INSTRUCTIONS
        self.assertIn("CLARA", _PLANNER_INSTRUCTIONS)
        self.assertIn("refuse", _PLANNER_INSTRUCTIONS)
        self.assertIn("{in_scope}", _PLANNER_INSTRUCTIONS)

    def test_refusal_templates_do_not_leak_internals(self):
        from app.assistant.persona import NO_INTERNALS, CLARA_CAPABILITIES
        self.assertNotIn("language model", CLARA_CAPABILITIES.lower())
        self.assertNotIn("system prompt", CLARA_CAPABILITIES.lower())
        self.assertIn("NEVER", NO_INTERNALS)


class TestContentSplitter(unittest.TestCase):
    def test_split_bedrock_blocks(self):
        from app.assistant.specialists import _split_reasoning_and_answer
        content = [
            {"type": "reasoning_content", "text": "thinking about the case"},
            {"type": "text", "text": "The answer is 42."},
        ]
        reasoning, answer = _split_reasoning_and_answer(content)
        self.assertEqual(reasoning, "thinking about the case")
        self.assertEqual(answer, "The answer is 42.")

    def test_split_inline_thinking_tags(self):
        from app.assistant.specialists import _split_reasoning_and_answer
        content = "<thinking>internal reasoning</thinking>The money went to account X."
        reasoning, answer = _split_reasoning_and_answer(content)
        self.assertEqual(reasoning, "internal reasoning")
        self.assertIn("account X", answer)

    def test_split_plain_text(self):
        from app.assistant.specialists import _split_reasoning_and_answer
        reasoning, answer = _split_reasoning_and_answer("just an answer")
        self.assertEqual(reasoning, "")
        self.assertEqual(answer, "just an answer")


class TestErrorClassification(unittest.TestCase):
    def test_transient_errors(self):
        from app.assistant.errors import classify_error, error_message
        cat, retryable = classify_error(TimeoutError("connection timed out"))
        self.assertEqual(cat, "transient")
        self.assertTrue(retryable)
        msg = error_message(cat, "en")
        self.assertIn("try again", msg.lower())

    def test_unsupported_errors(self):
        from app.assistant.errors import classify_error
        cat, retryable = classify_error(ValueError("syntax error in SQL"))
        self.assertEqual(cat, "unsupported")
        self.assertFalse(retryable)

    def test_provider_block_errors(self):
        from app.assistant.errors import classify_error
        cat, _ = classify_error(RuntimeError("content filter blocked the response"))
        self.assertEqual(cat, "provider_block")

    def test_generic_fallback(self):
        from app.assistant.errors import classify_error
        cat, retryable = classify_error(RuntimeError("some unknown error"))
        self.assertEqual(cat, "generic")
        self.assertTrue(retryable)

    def test_multilingual_messages(self):
        from app.assistant.errors import error_message
        en_msg = error_message("transient", "en")
        hi_msg = error_message("transient", "hi")
        kn_msg = error_message("transient", "kn")
        self.assertNotEqual(en_msg, hi_msg)
        self.assertNotEqual(en_msg, kn_msg)


class TestFileTools(unittest.TestCase):
    def setUp(self):
        from app.assistant.skills import files as files_mod
        self.files = files_mod
        self.run_id = "run-files-test"
        self.workdir = analysis.workspace_for(self.run_id)
        (self.workdir / "notes.txt").write_text("alpha\nbeta district\ngamma\n", encoding="utf-8")

    def tearDown(self):
        analysis.cleanup_run_workspace(self.run_id)

    def test_list_read_grep_and_escape_guard(self):
        tools = {t.name: t for t in self.files.build_file_tools(self.run_id)}
        listing = tools["list_files"].invoke({})
        self.assertIn("notes.txt", listing)

        body = tools["read_file"].invoke({"path": "notes.txt"})
        self.assertIn("alpha", body)

        hits = tools["grep"].invoke({"pattern": "district"})
        self.assertIn("notes.txt:2:", hits)

        denied = tools["read_file"].invoke({"path": "../secrets.txt"})
        self.assertIn("escapes", denied.lower())

        abs_denied = tools["read_file"].invoke({"path": "C:/Windows/System32/drivers/etc/hosts"})
        self.assertIn("Absolute", abs_denied)


class TestReportEngine(unittest.TestCase):
    def test_html_to_pdf_returns_bytes(self):
        from app.assistant.skills.report import html_to_pdf
        pdf = html_to_pdf("<html><body><h1>CLARA Report</h1><p>Test</p></body></html>")
        self.assertTrue(pdf.startswith(b"%PDF"), f"expected PDF magic, got {pdf[:20]!r}")


class TestCodeArgExtract(unittest.TestCase):
    def test_extract_code_arg_from_partial_json(self):
        from app.assistant.specialists import _extract_code_arg
        partial = '{"purpose": "chart", "code": "print(\\"hi\\")\\nimport plotly\\n'
        out = _extract_code_arg(partial)
        self.assertIn("print", out)
        self.assertIn("plotly", out)
        self.assertEqual(_extract_code_arg(""), "")
        self.assertEqual(_extract_code_arg('{"purpose":"x"}'), "")


if __name__ == "__main__":
    unittest.main(verbosity=2)
