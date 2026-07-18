"""Agent-written Python execution for demo analysis artifacts.

No sandbox by user choice: this runs in the same Python environment as the server, but
in a per-run working directory and a subprocess so timeouts can kill runaway code.

The workdir persists for the whole run (not a TemporaryDirectory per call), so later
steps -- and read_file/grep -- can see files generated earlier in the same turn.
"""
from __future__ import annotations

import logging
import os
import shutil
import subprocess
import sys
import tempfile
import textwrap
import uuid
from pathlib import Path

from langchain_core.tools import StructuredTool

from ...config import settings
from .. import persistence
from ..events import CodePayload, DocumentArtifact
from ..tools import CURRENT_EMITTER, _in_thread

logger = logging.getLogger(__name__)

_EXT_TO_FORMAT = {
    ".pdf": "pdf",
    ".png": "png",
    ".svg": "svg",
    ".csv": "csv",
    ".json": "json",
    ".html": "html",
    ".txt": "text",
    ".md": "text",
}

# Per-run workspaces live under the process temp dir so they die with the OS temp
# cleaner if we crash before cleanup_run_workspace runs.
WORKDIR_ROOT = Path(tempfile.gettempdir()) / "ksp-assistant-workspaces"


def workspace_for(run_id: str) -> Path:
    """Return (creating if needed) the persistent workdir for this run."""
    safe = "".join(c if c.isalnum() or c in "-_" else "_" for c in (run_id or "anon"))
    path = WORKDIR_ROOT / safe
    path.mkdir(parents=True, exist_ok=True)
    return path


def cleanup_run_workspace(run_id: str) -> None:
    """Drop the per-run workdir after the turn terminates. Best-effort."""
    safe = "".join(c if c.isalnum() or c in "-_" else "_" for c in (run_id or "anon"))
    path = WORKDIR_ROOT / safe
    if path.exists():
        try:
            shutil.rmtree(path, ignore_errors=True)
        except Exception:
            logger.debug("workspace cleanup failed for %s", run_id, exc_info=True)


def display_title_from_filename(name: str) -> str:
    """Human-readable artifact title: 'Cases by District.html' -> 'Cases by District'."""
    stem = Path(name).stem
    return stem.replace("_", " ").strip() or name


def build_python_tool(session_id: str, run_id: str) -> StructuredTool:
    workdir = workspace_for(run_id)
    # Track which files we've already published as artifacts so a second call that
    # leaves previous files in the workdir doesn't re-emit them.
    seen: set[str] = set()

    def _run_python(code: str, purpose: str = "analysis") -> str:
        code = textwrap.dedent(code or "").strip()
        if not code:
            return "No Python code supplied."
        emitter = CURRENT_EMITTER.get()
        # Unique script name per call so concurrent/sequential runs don't collide and
        # so we never collect a previous call's script as an artifact.
        script = workdir / f"_analysis_{uuid.uuid4().hex[:8]}.py"
        script.write_text(code, encoding="utf-8")

        def _execute(handle=None) -> str:
            step_id = getattr(handle, "id", None)
            if emitter:
                emitter.code(CodePayload(step_id=step_id, phase="executing", code=code, language="python"))
            env = {**os.environ, "MPLBACKEND": "Agg"}
            try:
                proc = subprocess.run(
                    [sys.executable, str(script)],
                    cwd=workdir,
                    env=env,
                    text=True,
                    capture_output=True,
                    timeout=settings.assistant_code_timeout_seconds,
                )
                stdout, stderr, exit_code = proc.stdout, proc.stderr, proc.returncode
            except subprocess.TimeoutExpired as exc:
                stdout = exc.stdout or ""
                stderr = (exc.stderr or "") + f"\nTimed out after {settings.assistant_code_timeout_seconds}s."
                exit_code = 124
            finally:
                try:
                    script.unlink(missing_ok=True)
                except Exception:
                    pass

            artifacts: list[str] = []
            for path in sorted(workdir.iterdir()):
                if not path.is_file() or path.name.startswith("_analysis_"):
                    continue
                # Skip already-published files from earlier calls in this run.
                key = f"{path.name}:{path.stat().st_mtime_ns}:{path.stat().st_size}"
                if key in seen:
                    continue
                fmt = _EXT_TO_FORMAT.get(path.suffix.lower())
                if not fmt:
                    continue
                seen.add(key)
                artifact_id = f"doc-{uuid.uuid4().hex[:8]}"
                title = display_title_from_filename(path.name)
                document = DocumentArtifact(
                    id=artifact_id,
                    title=title,
                    format=fmt,  # type: ignore[arg-type]
                    url=f"/api/v1/assistant/artifacts/{artifact_id}",
                    caption=f"Generated by Python for {purpose}.",
                )
                persistence.save_artifact(document, session_id, run_id)
                persistence.save_blob(artifact_id, path.read_bytes())
                artifacts.append(title)
                if handle:
                    handle.emit_artifact(document)

            if emitter:
                emitter.code(CodePayload(
                    step_id=step_id,
                    phase="done" if exit_code == 0 else "error",
                    language="python",
                    stdout=stdout[-20000:],
                    stderr=stderr[-12000:],
                    exit_code=exit_code,
                    success=exit_code == 0,
                ))
            if handle:
                handle.output = f"exit {exit_code}; {len(artifacts)} artifact(s)"
            return (
                f"Python exited {exit_code}. Generated {len(artifacts)} artifact(s): "
                f"{', '.join(artifacts) or 'none'}.\n"
                f"Workspace: {workdir}\n"
                f"STDOUT:\n{stdout[-4000:]}\nSTDERR:\n{stderr[-2000:]}"
            )

        if not emitter:
            return _execute(None)
        with emitter.step(
            "supervisor", "tool_call", "Running Python analysis",
            tool_name="run_python", tool_input={"purpose": purpose},
            detail=purpose,
        ) as handle:
            return _execute(handle)

    return StructuredTool.from_function(
        func=_run_python,
        coroutine=_in_thread(_run_python),
        name="run_python",
        description=(
            "Execute short Python analysis code in the server runtime and collect generated "
            "png/pdf/svg/csv/json/html files as artifacts. matplotlib, pandas and plotly ARE "
            "installed. Use for charts/graphs and small tabular analysis after SQL/Cypher/"
            "vector tools have gathered the data (paste the returned rows into the code as a "
            "Python literal). For on-screen interactive charts, use plotly and "
            "fig.write_html('Cases by District.html', include_plotlyjs=True) -- name files "
            "with spaces, never underscores. For charts destined for a PDF, use matplotlib "
            "and fig.savefig('Cases by District.png'). Never write an ASCII/text bar chart "
            "into a .txt file. Do not use for database queries; use the dedicated tools. "
            "Files persist in the run workspace across calls so later steps can read them."
        ),
    )
