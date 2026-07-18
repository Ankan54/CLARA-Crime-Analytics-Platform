import { useMemo } from "react";
import type { CodePayload } from "../../lib/assistantTypes";

/** Lightweight syntax-ish code frame. Uses <pre><code> with language class; highlight
 *  is applied via CSS (highlight.js theme loaded in index.css) + optional rehype in answers. */
export function CodeBlock({
  code,
  language = "python",
  phase,
  stdout,
  stderr,
}: {
  code?: string | null;
  language?: string;
  phase?: CodePayload["phase"];
  stdout?: string | null;
  stderr?: string | null;
}) {
  const label = useMemo(() => {
    if (phase === "template") return "Writing code…";
    if (phase === "executing") return "Executing…";
    if (phase === "error") return "Failed";
    if (phase === "done") return "Done";
    return language;
  }, [phase, language]);

  if (!code && !stdout && !stderr) return null;

  return (
    <div className={`assistant-code-frame${phase === "template" || phase === "executing" ? " is-streaming" : ""}`}>
      <header className="assistant-code-frame-header">
        <span className="assistant-code-lang">{language}</span>
        <span className="assistant-code-phase">{label}</span>
      </header>
      {code && (
        <pre className="assistant-code-body">
          <code className={`language-${language}`}>{code}</code>
        </pre>
      )}
      {stdout ? <pre className="assistant-code-stdout">{stdout}</pre> : null}
      {stderr ? <pre className="assistant-code-stderr">{stderr}</pre> : null}
    </div>
  );
}
