"""Runtime playbook skills for the assistant's own LLM agents.

Each SKILL.md becomes one tool. The frontmatter description is the trigger; the body is
loaded only when the model invokes that tool.
"""
from __future__ import annotations

import asyncio
import logging
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from langchain_core.tools import StructuredTool

from ..emitter import RunEmitter
from ..tools import CURRENT_EMITTER, CURRENT_SPECIALIST

logger = logging.getLogger(__name__)

PLAYBOOK_DIR = Path(__file__).parent / "playbooks"


@dataclass(frozen=True)
class Playbook:
    name: str
    description: str
    agents: frozenset[str]
    body: str


def _parse_list(value: str) -> frozenset[str]:
    return frozenset(item.strip() for item in value.split(",") if item.strip())


def _parse_skill(path: Path) -> Playbook | None:
    text = path.read_text(encoding="utf-8")
    if not text.startswith("---"):
        logger.warning("playbook %s has no frontmatter", path)
        return None
    try:
        _, raw_meta, body = text.split("---", 2)
    except ValueError:
        logger.warning("playbook %s has invalid frontmatter", path)
        return None
    meta: dict[str, str] = {}
    for line in raw_meta.splitlines():
        if ":" not in line:
            continue
        key, value = line.split(":", 1)
        meta[key.strip()] = value.strip().strip('"')
    name = meta.get("name") or path.parent.name
    desc = meta.get("description", "").strip()
    if not desc:
        logger.warning("playbook %s has empty description", path)
        return None
    return Playbook(name=name, description=desc, agents=_parse_list(meta.get("agents", "")), body=body.strip())


def load_playbooks(agent: str | None = None) -> list[Playbook]:
    if not PLAYBOOK_DIR.exists():
        return []
    out: list[Playbook] = []
    for skill_path in sorted(PLAYBOOK_DIR.glob("*/SKILL.md")):
        playbook = _parse_skill(skill_path)
        if not playbook:
            continue
        if agent and playbook.agents and agent not in playbook.agents:
            continue
        out.append(playbook)
    return out


def build_playbook_tools(agent: str | None = None) -> list[StructuredTool]:
    tools: list[StructuredTool] = []
    for playbook in load_playbooks(agent):

        def _make_loader(_playbook: Playbook):
            def _load_playbook() -> str:
                emitter = CURRENT_EMITTER.get()
                if emitter:
                    with emitter.step(
                        "supervisor", "tool_call", f"Playbook: {_playbook.name}",
                        specialist=CURRENT_SPECIALIST.get(),
                        tool_name=_playbook.name, tool_input={},
                        detail=_playbook.description,
                    ) as handle:
                        handle.output = "Loaded step-by-step workflow"
                return (
                    "IMPORTANT: This playbook is workflow instruction, not answer text. "
                    "Do not copy its English headings or bullets into the final answer. "
                    "After following the steps, write the final answer in the officer's selected language.\n\n"
                    + _playbook.body
                )

            async def _load_playbook_async() -> str:
                return await asyncio.to_thread(_load_playbook)

            return _load_playbook, _load_playbook_async

        loader, loader_async = _make_loader(playbook)

        tools.append(StructuredTool.from_function(
            func=loader,
            coroutine=loader_async,
            name=f"skill_{playbook.name.replace('-', '_')}",
            description=playbook.description,
            parse_docstring=False,
        ))
    return tools
