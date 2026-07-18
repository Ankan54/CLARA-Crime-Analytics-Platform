import { useEffect, useState } from "react";
import type { DocumentArtifact } from "../../lib/assistantTypes";
import { AssistantIcon } from "./icons";

/** Minimal comma-separated parser -- good enough for the demo's plain evidence CSVs. */
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

function useFetchedText(url: string | undefined, enabled: boolean): { text: string | null; loading: boolean; error: string | null } {
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

export function DocumentArtifactView({ artifact }: { artifact: DocumentArtifact }) {
  const needsFetch = (artifact.format === "csv" || artifact.format === "text" || artifact.format === "html" || artifact.format === "json" || artifact.format === "svg") && !artifact.text && !!artifact.url;
  const { text: fetchedText, loading, error } = useFetchedText(artifact.url, needsFetch);
  const bodyText = artifact.text ?? fetchedText;

  if (artifact.format === "pdf") {
    if (!artifact.url) {
      return <EmptyDocumentNote format="PDF" />;
    }
    return (
      <div className="document-artifact document-pdf">
        <iframe src={artifact.url} title={artifact.title} />
      </div>
    );
  }

  if (artifact.format === "png") {
    if (!artifact.url) {
      return <EmptyDocumentNote format="PNG" />;
    }
    return (
      <div className="document-artifact document-image">
        <img src={artifact.url} alt={artifact.title} />
      </div>
    );
  }

  if (artifact.format === "docx") {
    return (
      <div className="document-artifact document-fallback">
        <AssistantIcon name="document" />
        <p>
          DOCX files can't be previewed inline yet.
          {artifact.url ? (
            <>
              {" "}
              <a href={artifact.url} target="_blank" rel="noreferrer">
                Download {artifact.title}
              </a>
            </>
          ) : (
            " No sample file is attached in this demo build."
          )}
        </p>
      </div>
    );
  }

  if (loading) {
    return <p className="muted">Loading {artifact.title}…</p>;
  }
  if (error) {
    return <p className="alert alert-danger">{error}</p>;
  }
  if (!bodyText) {
    return <EmptyDocumentNote format={artifact.format.toUpperCase()} />;
  }

  if (artifact.format === "csv") {
    const { columns, rows } = parseCsv(bodyText);
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

  if (artifact.format === "html" || artifact.format === "svg") {
    return (
      <div className="document-artifact document-html">
        <iframe srcDoc={bodyText} title={artifact.title} sandbox="allow-scripts" />
      </div>
    );
  }

  return (
    <div className="document-artifact document-text">
      <pre>{bodyText}</pre>
    </div>
  );
}

function EmptyDocumentNote({ format }: { format: string }) {
  return (
    <div className="document-artifact document-fallback">
      <AssistantIcon name="document" />
      <p>No {format} preview available in this demo build.</p>
    </div>
  );
}
