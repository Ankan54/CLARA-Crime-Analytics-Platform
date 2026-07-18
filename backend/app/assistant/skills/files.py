"""Pure-Python file tools scoped to a run's workspace and its generated artifacts.

No shell: Windows and Linux both work the same way. Paths that escape the workdir are
rejected (same contract as the reference VFS resolve_vfs_path).
"""
from __future__ import annotations

import re
from pathlib import Path
from typing import Any

from langchain_core.tools import StructuredTool

from .. import bus, persistence
from ..tools import CURRENT_EMITTER, _in_thread
from .analysis import workspace_for

_READ_TRUNCATE_CHARS = 20_000
_GREP_MAX_MATCHES = 200
_TEXT_FORMATS = frozenset({"text", "csv", "html", "json", "svg"})


def _resolve_in_workspace(workdir: Path, path: str) -> Path:
    """Resolve `path` under workdir; raise ValueError on escape or missing file."""
    raw = (path or "").strip().replace("\\", "/")
    if not raw or raw.startswith("/") or re.match(r"^[A-Za-z]:", raw):
        raise ValueError(f"Absolute paths are not allowed: {path!r}")
    if ".." in Path(raw).parts:
        raise ValueError(f"Path escapes the workspace: {path!r}")
    full = (workdir / raw).resolve()
    base = workdir.resolve()
    if full != base and base not in full.parents:
        raise ValueError(f"Path escapes the workspace: {path!r}")
    return full


def build_file_tools(run_id: str) -> list[StructuredTool]:
    workdir = workspace_for(run_id)

    def _list_files() -> str:
        files = sorted(p.name for p in workdir.iterdir() if p.is_file() and not p.name.startswith("_analysis_"))
        arts = bus.artifacts_of(run_id)
        lines = [f"Workspace ({workdir}):"]
        lines.extend(f"  - {name}" for name in files) if files else lines.append("  (empty)")
        if arts:
            lines.append("Artifacts this run:")
            for a in arts:
                lines.append(
                    f"  - id={a.get('id')} title={a.get('title')!r} format={a.get('format')} "
                    f"url={a.get('url') or ''}"
                )
        return "\n".join(lines)

    def _read_file(path: str, start_line: int = 0, end_line: int = 0) -> str:
        try:
            target = _resolve_in_workspace(workdir, path)
        except ValueError as exc:
            return str(exc)
        if not target.is_file():
            return f"File not found: {path}"
        try:
            text = target.read_text(encoding="utf-8", errors="replace")
        except Exception as exc:
            return f"Could not read {path}: {exc}"
        lines = text.splitlines()
        if start_line or end_line:
            start = max(1, start_line or 1) - 1
            end = end_line if end_line > 0 else len(lines)
            lines = lines[start:end]
            text = "\n".join(lines)
        if len(text) > _READ_TRUNCATE_CHARS:
            text = text[:_READ_TRUNCATE_CHARS] + f"\n... [truncated at {_READ_TRUNCATE_CHARS} chars]"
        return text or "(empty file)"

    def _grep(pattern: str, path: str = "") -> str:
        try:
            regex = re.compile(pattern)
        except re.error:
            regex = re.compile(re.escape(pattern))
        targets: list[Path]
        if path:
            try:
                one = _resolve_in_workspace(workdir, path)
            except ValueError as exc:
                return str(exc)
            if not one.is_file():
                return f"File not found: {path}"
            targets = [one]
        else:
            targets = [p for p in sorted(workdir.iterdir()) if p.is_file() and not p.name.startswith("_analysis_")]
        matches: list[str] = []
        for file in targets:
            try:
                for i, line in enumerate(file.read_text(encoding="utf-8", errors="replace").splitlines(), 1):
                    if regex.search(line):
                        matches.append(f"{file.name}:{i}: {line[:400]}")
                        if len(matches) >= _GREP_MAX_MATCHES:
                            return "\n".join(matches) + f"\n... [capped at {_GREP_MAX_MATCHES} matches]"
            except Exception:
                continue
        return "\n".join(matches) if matches else "No matches."

    def _read_artifact(artifact_id: str) -> str:
        arts = {a.get("id"): a for a in bus.artifacts_of(run_id)}
        art = arts.get(artifact_id)
        row = persistence.load_artifact(artifact_id)
        if not art and not row:
            return f"Unknown artifact_id: {artifact_id}. Call list_files to see available artifacts."
        fmt = ((art or {}).get("format") or (row or {}).get("kind") or "").lower()
        # DocumentArtifact stores format inside body JSON.
        if row and isinstance(row.get("body"), dict):
            fmt = (row["body"].get("format") or fmt).lower()
            title = row["body"].get("title") or row.get("title") or artifact_id
            url = row["body"].get("url") or f"/api/v1/assistant/artifacts/{artifact_id}"
        else:
            title = (art or {}).get("title") or (row or {}).get("title") or artifact_id
            url = (art or {}).get("url") or f"/api/v1/assistant/artifacts/{artifact_id}"
        if fmt not in _TEXT_FORMATS and fmt not in ("svg", "document"):
            if fmt in ("png", "pdf", "docx") or (row and row.get("blob") and fmt not in _TEXT_FORMATS):
                return (
                    f"Artifact '{title}' (id={artifact_id}, format={fmt or 'binary'}) is binary. "
                    f"Available at {url}. Reference it by id/title; do not ask to print its bytes."
                )
        blob = (row or {}).get("blob") if row else None
        if blob is None and art and art.get("text"):
            return str(art["text"])[:_READ_TRUNCATE_CHARS]
        if blob is None:
            return f"Artifact '{title}' (id={artifact_id}) has no inline body. URL: {url}"
        text = blob.decode("utf-8", errors="replace") if isinstance(blob, (bytes, bytearray)) else str(blob)
        if len(text) > _READ_TRUNCATE_CHARS:
            text = text[:_READ_TRUNCATE_CHARS] + f"\n... [truncated at {_READ_TRUNCATE_CHARS} chars]"
        return text

    def _wrap(fn, name: str, description: str, **kwargs: Any) -> StructuredTool:
        return StructuredTool.from_function(
            func=fn, coroutine=_in_thread(fn), name=name, description=description, **kwargs
        )

    return [
        _wrap(
            _list_files, "list_files",
            "List files in this run's workspace and the artifacts already generated this turn "
            "(id, title, format, url). Use before read_file/read_artifact when you need to "
            "refer to a chart, table, or report you (or another specialist) already produced.",
        ),
        _wrap(
            _read_file, "read_file",
            "Read a text file from this run's workspace by relative path. Optional start_line/"
            "end_line (1-indexed) for a slice. Paths cannot escape the workspace.",
        ),
        _wrap(
            _grep, "grep",
            "Search files in this run's workspace for a regex (or literal) pattern. Optional "
            "path limits the search to one file; omit it to search all workspace files. "
            "Returns 'filename:lineno: line' matches.",
        ),
        _wrap(
            _read_artifact, "read_artifact",
            "Read a previously generated artifact by its id (from list_files or the artifacts "
            "context). Returns text for csv/html/json/text; for binary formats (png/pdf) returns "
            "a short note with the URL so you can reference it without printing bytes.",
        ),
    ]
