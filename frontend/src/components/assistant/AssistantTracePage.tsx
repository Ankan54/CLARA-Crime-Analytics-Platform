import { useMemo, useState } from "react";
import type { AssistantLanguage, AssistantRunTrace, AssistantStep, AssistantTraceEvent } from "../../lib/assistantTypes";
import { uiText } from "../../data/assistantTranslations";
import { AssistantIcon } from "./icons";
import { ReasoningTrail } from "./ReasoningTrail";

interface AssistantTracePageProps {
  trace: AssistantRunTrace | null;
  runId: string | null;
  language: AssistantLanguage;
  onBack: () => void;
}

function eventTone(event: AssistantTraceEvent): "ok" | "warn" | "danger" | "neutral" {
  if (event.type === "done") return "ok";
  if (event.type === "error") return "danger";
  if (event.type === "run_started") return "warn";
  return "neutral";
}

export function AssistantTracePage({ trace, runId, language, onBack }: AssistantTracePageProps) {
  const copy = uiText(language);
  const [showRaw, setShowRaw] = useState(false);
  const orderedEvents = useMemo(
    () => (trace?.events ?? []).slice().sort((a, b) => a.seq - b.seq),
    [trace?.events],
  );
  const stepEvents = useMemo<AssistantStep[]>(
    () =>
      orderedEvents.reduce<AssistantStep[]>((acc, event) => {
        if (event.type !== "step" || !event.payload || typeof event.payload !== "object") {
          return acc;
        }
        const maybeStep = (event.payload as { step?: AssistantStep }).step;
        if (maybeStep) {
          acc.push(maybeStep);
        }
        return acc;
      }, []),
    [orderedEvents],
  );

  if (!trace) {
    return (
      <section className="assistant-trace-page">
        <header className="assistant-trace-head">
          <button type="button" className="btn btn-ghost btn-sm" onClick={onBack}>
            <AssistantIcon name="chevron-left" />
            Back to chat
          </button>
          <div>
            <p className="kicker">{copy.traceTitle}</p>
            <h2>{copy.noTrace}</h2>
          </div>
        </header>
        {runId && <p className="mono muted">Run ID: {runId}</p>}
      </section>
    );
  }

  return (
    <section className="assistant-trace-page">
      <header className="assistant-trace-head">
        <div className="assistant-trace-head-main">
          <button type="button" className="btn btn-ghost btn-sm" onClick={onBack}>
            <AssistantIcon name="chevron-left" />
            Back to chat
          </button>
          <div>
            <p className="kicker">{copy.traceDemo}</p>
            <h2>{copy.traceTitle}</h2>
            <p className="muted">{copy.traceSubtitle}</p>
          </div>
        </div>
        <div className="assistant-trace-head-meta">
          <div className={`status-pill ${trace.status === "error" ? "danger" : trace.status === "complete" ? "ok" : "warn"}`}>
            {trace.status}
          </div>
          <p className="mono">Run ID: {trace.runId}</p>
          <p className="muted small">
            {orderedEvents.length} {copy.traceCount}
          </p>
          <label className="assistant-trace-raw-toggle">
            <input type="checkbox" checked={showRaw} onChange={(event) => setShowRaw(event.target.checked)} />
            <span>{copy.rawMode}</span>
          </label>
        </div>
      </header>

      <ReasoningTrail steps={stepEvents} streaming={trace.status === "streaming"} />

      <div className="assistant-trace-list">
        {orderedEvents.map((event) => (
          <article key={event.id} className="assistant-trace-item">
            <div className="assistant-trace-item-head">
              <span className="assistant-trace-seq">#{String(event.seq).padStart(2, "0")}</span>
              <div className={`status-pill ${eventTone(event)}`}>{event.type}</div>
              <time className="mono muted">{new Date(event.at).toLocaleTimeString()}</time>
            </div>
            <p>{event.summary}</p>
            {!showRaw && event.type === "step" && (
              <TraceStepDetails payload={event.payload} />
            )}
            {showRaw && (
              <pre className="assistant-trace-raw">
                {JSON.stringify(event.payload, null, 2)}
              </pre>
            )}
          </article>
        ))}
      </div>
    </section>
  );
}

function TraceStepDetails({ payload }: { payload: unknown }) {
  if (!payload || typeof payload !== "object" || !("step" in payload)) {
    return null;
  }
  const step = (payload as { step?: { detail?: string; query?: string } }).step;
  if (!step) return null;
  return (
    <div className="assistant-trace-step-meta">
      {step.detail && <p className="muted small">{step.detail}</p>}
      {step.query && <code className="assistant-trace-query">{step.query}</code>}
    </div>
  );
}
