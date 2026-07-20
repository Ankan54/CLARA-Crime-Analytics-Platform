import { useEffect, useState } from "react";
import type { AgentKind, AssistantStep, PlanPayload } from "../../lib/assistantTypes";
import { AssistantIcon } from "./icons";
import { CodeBlock } from "./CodeBlock";
import { Markdown } from "./Markdown";

const AGENT_LABELS: Record<AgentKind, string> = {
  supervisor: "CLARA",
  sql: "Records",
  graph: "Network",
  vector: "Similar cases",
  legal: "Legal",
};

// Tool args the officer should read as prose vs. code vs. noise.
const INPUT_DESC_KEYS = ["purpose", "subtask", "question", "description"];
const INPUT_NOISE_KEYS = new Set(["purpose", "subtask", "question", "description", "sql", "cypher", "query", "code", "gate", "error", "stripped"]);

/** Render tool-call arguments as a readable summary instead of a raw JSON blob.
 *  The human-readable intent (purpose/subtask) leads; the actual SQL/Cypher/code is
 *  shown separately via step.query / step.code, so we skip it here to avoid duplication.
 *  P8: when a real query string is present (step.query), the scalar param list only
 *  restates it -- suppress it so each step shows ONE query representation. */
function ToolInputView({ input, suppressParams }: { input: Record<string, unknown>; suppressParams: boolean }) {
  const desc = INPUT_DESC_KEYS.map((k) => input[k]).find((v) => typeof v === "string" && v.trim()) as string | undefined;
  const extras = suppressParams
    ? []
    : Object.entries(input).filter(
        ([k, v]) =>
          !INPUT_NOISE_KEYS.has(k) &&
          v != null &&
          // Skip blank strings (an omitted/defaulted arg like text_query="") -- they show as
          // an empty param row and read as "an empty query was run".
          ((typeof v === "string" && v.trim() !== "") || typeof v === "number" || typeof v === "boolean"),
      );
  if (!desc && extras.length === 0) return null;
  return (
    <div className="reasoning-step-input">
      {desc && <Markdown className="reasoning-step-detail reasoning-step-md">{desc}</Markdown>}
      {extras.length > 0 && (
        <dl className="reasoning-step-params">
          {extras.map(([k, v]) => (
            <div key={k}>
              <dt>{k}</dt>
              <dd>{String(v)}</dd>
            </div>
          ))}
        </dl>
      )}
    </div>
  );
}

function stepStatusLabel(step: AssistantStep): string {
  if (step.status === "running") return "Working…";
  if (step.status === "error") return "Failed";
  return "Done";
}

function StepStatusIcon({ status }: { status: AssistantStep["status"] }) {
  if (status === "running") {
    return <span className="reasoning-step-status-icon is-running" aria-hidden="true" />;
  }
  if (status === "error") {
    return <span className="reasoning-step-status-icon is-error" aria-label="Failed">✕</span>;
  }
  return <span className="reasoning-step-status-icon is-done" aria-label="Done">✓</span>;
}

function ReasoningStepCard({ step, index }: { step: AssistantStep; index: number }) {
  const [open, setOpen] = useState(step.status === "running");

  useEffect(() => {
    // Auto-expand while running; auto-collapse once done (mirrors the outer trail).
    if (step.status === "running") setOpen(true);
    else setOpen(false);
  }, [step.status]);

  const hasBody = Boolean(
    step.detail || step.toolName || step.toolInput || step.query || step.retrieval || step.code || step.output,
  );

  return (
    <article className={`reasoning-step ${step.agent}${step.status === "running" ? " running" : ""}${open ? " is-open" : " is-collapsed"}`}>
      <button
        type="button"
        className="reasoning-step-toggle"
        onClick={() => setOpen((v) => !v)}
        aria-expanded={open}
      >
        <span className="reasoning-step-index">{String(index + 1).padStart(2, "0")}</span>
        <span className="reasoning-step-agent">{step.specialist ?? AGENT_LABELS[step.agent]}</span>
        <strong className="reasoning-step-title">{step.title}</strong>
        <StepStatusIcon status={step.status} />
        <span className="reasoning-step-status">{stepStatusLabel(step)}</span>
        {hasBody && <AssistantIcon name="chevron-down" className="reasoning-step-chevron" />}
      </button>

      {open && hasBody && (
        <div className="reasoning-step-body">
          {step.detail && (
            <Markdown className="reasoning-step-detail reasoning-step-md">{step.detail}</Markdown>
          )}
          {step.toolName && <small className="reasoning-step-tool">{step.toolName}</small>}
          {step.toolInput && Object.keys(step.toolInput).length > 0 && (
            <ToolInputView input={step.toolInput} suppressParams={Boolean(step.query)} />
          )}
          {step.query && <pre className="reasoning-step-query"><code>{step.query}</code></pre>}
          {step.retrieval && (
            <div className="reasoning-step-retrieval">
              <strong>{step.retrieval.count} result{step.retrieval.count === 1 ? "" : "s"}</strong>
              {step.retrieval.sources.length > 0 && <span> from {step.retrieval.sources.join(", ")}</span>}
              {step.retrieval.chunks.length > 0 && (
                <ul>
                  {step.retrieval.chunks.slice(0, 4).map((chunk, chunkIndex) => (
                    <li key={`${chunk.caseRef ?? chunk.source ?? chunkIndex}-${chunkIndex}`}>
                      <span>{chunk.caseRef ?? chunk.source ?? "Source"}</span>
                      {typeof chunk.score === "number" && <code>{chunk.score.toFixed(3)}</code>}
                      {chunk.snippet && <small>{chunk.snippet}</small>}
                    </li>
                  ))}
                </ul>
              )}
            </div>
          )}
          {step.code && (
            <CodeBlock
              code={step.code.code}
              language={step.code.language || "python"}
              phase={step.code.phase}
              stdout={step.code.stdout}
              stderr={step.code.stderr}
            />
          )}
          {step.output && (
            <Markdown className="reasoning-step-output reasoning-step-md">{step.output}</Markdown>
          )}
        </div>
      )}
    </article>
  );
}

/** Claude-desktop-style collapsible "thinking" panel: every route/tool-call/result the agents took. */
export function ReasoningTrail({ steps, plan, streaming }: { steps: AssistantStep[]; plan?: PlanPayload; streaming: boolean }) {
  const [expanded, setExpanded] = useState(true);
  const [autoCollapsed, setAutoCollapsed] = useState(false);

  useEffect(() => {
    if (!streaming && !autoCollapsed && steps.length > 0) {
      setExpanded(false);
      setAutoCollapsed(true);
    }
  }, [streaming, autoCollapsed, steps.length]);

  if (steps.length === 0) {
    return null;
  }

  const runningCount = steps.filter((step) => step.status === "running").length;

  return (
    <div className={`reasoning-trail${expanded ? " expanded" : ""}`}>
      <button
        type="button"
        className="reasoning-trail-toggle"
        onClick={() => setExpanded((current) => !current)}
        aria-expanded={expanded}
      >
        <span className={`reasoning-trail-dot${runningCount > 0 ? " pulse" : ""}`} />
        <span className="reasoning-trail-toggle-label">
          {streaming ? "Thinking…" : `Reasoned across ${steps.length} step${steps.length === 1 ? "" : "s"}`}
        </span>
        <AssistantIcon name="chevron-down" className="reasoning-trail-chevron" />
      </button>

      {expanded && (
        <div className="reasoning-trail-body">
          {plan && plan.tasks.length > 0 && (
            <div className="reasoning-plan">
              {plan.tasks.map((task) => (
                <span key={task.id} className={`reasoning-plan-task ${task.status}`}>
                  {task.title}
                </span>
              ))}
            </div>
          )}
          {steps.map((step, index) => (
            <ReasoningStepCard key={step.id} step={step} index={index} />
          ))}
          {streaming && (
            <div className="thinking-loader reasoning-trail-loader" role="status" aria-label="Thinking">
              <span className="thinking-dot" />
              <span className="thinking-dot" />
              <span className="thinking-dot" />
              <span className="thinking-loader-label">Thinking…</span>
            </div>
          )}
        </div>
      )}
    </div>
  );
}
