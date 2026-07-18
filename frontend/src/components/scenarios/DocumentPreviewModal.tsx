import { useEffect, useMemo, useState } from "react";
import type { ScenarioDocument } from "../../data/scenarios";
import { AssistantIcon } from "../assistant/icons";

function parseCsv(text: string): { columns: string[]; rows: string[][] } {
  const lines = text.split(/\r?\n/).filter((line) => line.trim().length > 0);
  if (lines.length === 0) {
    return { columns: [], rows: [] };
  }
  const [headerLine, ...rest] = lines;
  const columns = headerLine.split(",").map((cell) => cell.trim());
  const rows = rest.map((line) => line.split(",").map((cell) => cell.trim()));
  return { columns, rows };
}

function previewFormat(doc: ScenarioDocument): "text" | "csv" | "html" {
  const lower = doc.name.toLowerCase();
  if (lower.endsWith(".csv")) return "csv";
  if (lower.endsWith(".html") || lower.endsWith(".htm")) return "html";
  return "text";
}

function useFetchedText(url: string | undefined, enabled: boolean) {
  const [text, setText] = useState<string | null>(null);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    if (!url || !enabled) {
      return;
    }
    let cancelled = false;
    setLoading(true);
    setError(null);
    fetch(url)
      .then((res) => {
        if (!res.ok) throw new Error(`Could not load file (${res.status}).`);
        return res.text();
      })
      .then((body) => {
        if (!cancelled) setText(body);
      })
      .catch((err) => {
        if (!cancelled) setError(err instanceof Error ? err.message : "Failed to load file.");
      })
      .finally(() => {
        if (!cancelled) setLoading(false);
      });
    return () => {
      cancelled = true;
    };
  }, [url, enabled]);

  return { text, loading, error };
}

function DocumentPreviewBody({ doc }: { doc: ScenarioDocument }) {
  const format = previewFormat(doc);
  const { text, loading, error } = useFetchedText(doc.path, true);

  if (loading) {
    return <p className="muted briefing-preview-status">Loading {doc.label}…</p>;
  }
  if (error) {
    return <p className="alert alert-danger">{error}</p>;
  }
  if (!text) {
    return <p className="muted briefing-preview-status">No preview available.</p>;
  }

  if (format === "csv") {
    const { columns, rows } = parseCsv(text);
    return (
      <div className="document-artifact document-csv">
        <div className="table-wrap">
          <table>
            <thead>
              <tr>
                {columns.map((column) => (
                  <th key={column}>{column}</th>
                ))}
              </tr>
            </thead>
            <tbody>
              {rows.map((row, rowIndex) => (
                <tr key={rowIndex}>
                  {row.map((cell, cellIndex) => (
                    <td key={cellIndex}>{cell || "—"}</td>
                  ))}
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      </div>
    );
  }

  if (format === "html") {
    return (
      <div className="document-artifact document-html">
        <iframe srcDoc={text} title={doc.label} sandbox="" />
      </div>
    );
  }

  return (
    <div className="document-artifact document-text">
      <pre>{text}</pre>
    </div>
  );
}

export function DocumentPreviewModal({
  open,
  documents,
  activeName,
  scenarioTitle,
  onSelect,
  onClose,
}: {
  open: boolean;
  documents: ScenarioDocument[];
  activeName: string | null;
  scenarioTitle: string;
  onSelect: (name: string) => void;
  onClose: () => void;
}) {
  const activeDoc = useMemo(
    () => documents.find((doc) => doc.name === activeName) ?? documents[0] ?? null,
    [documents, activeName],
  );

  useEffect(() => {
    if (!open) {
      return;
    }
    function onKey(event: KeyboardEvent) {
      if (event.key === "Escape") {
        onClose();
        return;
      }
      if (!activeDoc || documents.length < 2) {
        return;
      }
      const index = documents.findIndex((doc) => doc.name === activeDoc.name);
      if (event.key === "ArrowDown" || event.key === "ArrowRight") {
        event.preventDefault();
        const next = documents[(index + 1) % documents.length];
        onSelect(next.name);
      }
      if (event.key === "ArrowUp" || event.key === "ArrowLeft") {
        event.preventDefault();
        const prev = documents[(index - 1 + documents.length) % documents.length];
        onSelect(prev.name);
      }
    }
    window.addEventListener("keydown", onKey);
    const prev = document.body.style.overflow;
    document.body.style.overflow = "hidden";
    return () => {
      window.removeEventListener("keydown", onKey);
      document.body.style.overflow = prev;
    };
  }, [open, onClose, onSelect, documents, activeDoc]);

  if (!open || !activeDoc) {
    return null;
  }

  return (
    <div className="briefing-preview-backdrop" role="presentation" onClick={onClose}>
      <div
        className="briefing-preview"
        role="dialog"
        aria-modal="true"
        aria-labelledby="briefing-preview-title"
        onClick={(event) => event.stopPropagation()}
      >
        <header className="briefing-preview-head">
          <div className="briefing-preview-title-block">
            <h3 id="briefing-preview-title">{activeDoc.label}</h3>
            <p className="muted mono">{scenarioTitle} · {activeDoc.name}</p>
          </div>
          <button type="button" className="btn btn-ghost" onClick={onClose} aria-label="Close preview">
            <AssistantIcon name="close" />
          </button>
        </header>
        <div className="briefing-preview-body">
          <nav className="briefing-preview-files" aria-label="Case file documents">
            {documents.map((doc) => (
              <button
                key={doc.name}
                type="button"
                className={`briefing-preview-file${doc.name === activeDoc.name ? " active" : ""}`}
                onClick={() => onSelect(doc.name)}
              >
                <span className="briefing-doc-kind">{doc.fileType.toUpperCase()}</span>
                <span>{doc.label}</span>
              </button>
            ))}
          </nav>
          <div className="briefing-preview-pane">
            <DocumentPreviewBody key={activeDoc.name} doc={activeDoc} />
          </div>
        </div>
      </div>
    </div>
  );
}
