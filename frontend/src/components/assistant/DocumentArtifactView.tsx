import { useEffect, useState } from "react";
import type { DocumentArtifact } from "../../lib/assistantTypes";
import { resolveApiUrl } from "../../lib/api";
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

function downloadFilename(title: string, extension: string): string {
  const base = title
    .trim()
    .replace(/[^\w.\-]+/g, "_")
    .replace(/_+/g, "_")
    .replace(/^_|_$/g, "")
    .slice(0, 80);
  const safe = base || "artifact";
  return safe.toLowerCase().endsWith(`.${extension}`) ? safe : `${safe}.${extension}`;
}

function downloadTextFile(title: string, text: string, extension: string, mime: string): void {
  const blob = new Blob([text], { type: mime });
  const url = URL.createObjectURL(blob);
  const anchor = document.createElement("a");
  anchor.href = url;
  anchor.download = downloadFilename(title, extension);
  anchor.click();
  URL.revokeObjectURL(url);
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
  // Resolve the backend-relative artifact URL against the API origin (see resolveApiUrl):
  // a raw "/api/..." would otherwise load from the frontend origin / Vite proxy and 404.
  const resolvedUrl = resolveApiUrl(artifact.url);
  const needsFetch = (artifact.format === "csv" || artifact.format === "text" || artifact.format === "html" || artifact.format === "json" || artifact.format === "svg") && !artifact.text && !!resolvedUrl;
  const { text: fetchedText, loading, error } = useFetchedText(resolvedUrl, needsFetch);
  const bodyText = artifact.text ?? fetchedText;

  if (artifact.format === "pdf") {
    if (!resolvedUrl) {
      return <EmptyDocumentNote format="PDF" />;
    }
    return (
      <div className="document-artifact document-pdf">
        <div className="document-artifact-toolbar">
          <a className="btn btn-ghost btn-sm" href={resolvedUrl} download={downloadFilename(artifact.title, "pdf")}>
            <AssistantIcon name="download" /> Download
          </a>
        </div>
        <iframe src={resolvedUrl} title={artifact.title} />
      </div>
    );
  }

  if (artifact.format === "png") {
    if (!resolvedUrl) {
      return <EmptyDocumentNote format="PNG" />;
    }
    return (
      <div className="document-artifact document-image">
        <div className="document-artifact-toolbar">
          <a className="btn btn-ghost btn-sm" href={resolvedUrl} download={downloadFilename(artifact.title, "png")}>
            <AssistantIcon name="download" /> Download
          </a>
        </div>
        <img src={resolvedUrl} alt={artifact.title} />
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
        <div className="document-artifact-toolbar">
          <button
            type="button"
            className="btn btn-ghost btn-sm"
            onClick={() => downloadTextFile(artifact.title, bodyText, "csv", "text/csv;charset=utf-8")}
          >
            <AssistantIcon name="download" /> Download
          </button>
        </div>
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
    const extension = artifact.format === "svg" ? "svg" : "html";
    const mime = artifact.format === "svg" ? "image/svg+xml;charset=utf-8" : "text/html;charset=utf-8";
    return (
      <div className="document-artifact document-html">
        <div className="document-artifact-toolbar">
          <button
            type="button"
            className="btn btn-ghost btn-sm"
            onClick={() => downloadTextFile(artifact.title, bodyText, extension, mime)}
          >
            <AssistantIcon name="download" /> Download
          </button>
        </div>
        <iframe srcDoc={bodyText} title={artifact.title} sandbox="allow-scripts" />
      </div>
    );
  }

  return (
    <div className="document-artifact document-text">
      <div className="document-artifact-toolbar">
        <button
          type="button"
          className="btn btn-ghost btn-sm"
          onClick={() =>
            downloadTextFile(
              artifact.title,
              bodyText,
              artifact.format === "json" ? "json" : "txt",
              artifact.format === "json" ? "application/json;charset=utf-8" : "text/plain;charset=utf-8",
            )
          }
        >
          <AssistantIcon name="download" /> Download
        </button>
      </div>
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
