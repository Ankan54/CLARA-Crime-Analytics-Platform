import type { PipelineRun } from "../../lib/api";

type Tone = "neutral" | "ok" | "warn" | "danger";

type Props = {
  run: PipelineRun;
  formatDate: (value?: string) => string;
  statusTone: (status?: string) => Tone;
  onRetry: () => void;
  onClear: () => void;
};

type FlowStep = {
  id: string;
  label: string;
  state: "done" | "active" | "pending" | "failed";
};

const LOAD_STAGES = new Set([
  "LOAD_START",
  "SQL_LOAD",
  "GRAPH_LOAD",
  "VECTOR_LOAD",
  "WRITEBACK",
  "FILE_DONE",
  "ARCHIVING",
  "DONE",
]);

const FILE_DONE_STAGES = new Set([
  "CHECKPOINTED",
  "EXTRACT_DONE",
  "FILE_DONE",
  "DONE",
  "REVIEW_PENDING",
]);

function flowSteps(run: PipelineRun): FlowStep[] {
  const status = run.status;
  const stage = run.current_stage || "";
  const failed = status === "FAILED";
  const completed =
    status === "COMPLETED" || status === "COMPLETED_WITH_REVIEW_PENDING";
  const review = status === "REVIEW_PENDING";
  const loading =
    !completed &&
    !review &&
    (run.phase === "load" || LOAD_STAGES.has(stage) || (failed && LOAD_STAGES.has(stage)));

  let activeIndex = 0;
  if (completed) activeIndex = 3;
  else if (loading) activeIndex = 2;
  else if (review) activeIndex = 1;
  else activeIndex = 0;

  const labels = ["Read documents", "Your review", "Save to systems", "Complete"];
  return labels.map((label, index) => {
    let state: FlowStep["state"] = "pending";
    if (completed || index < activeIndex) state = "done";
    else if (index === activeIndex) state = failed ? "failed" : "active";
    return { id: `step-${index}`, label, state };
  });
}

function fileRowState(
  progress: { stage?: string; status?: string },
  runActive: boolean,
): "done" | "active" | "pending" {
  const stage = progress.stage || "";
  const status = progress.status || "";
  if (
    FILE_DONE_STAGES.has(stage) ||
    status === "COMPLETED" ||
    status === "REVIEW_PENDING" ||
    status === "CHECKPOINTED"
  ) {
    return "done";
  }
  if (runActive && (status === "RUNNING" || status === "QUEUED" || (stage && !FILE_DONE_STAGES.has(stage)))) {
    return "active";
  }
  return "pending";
}

export function IngestRunStatus({ run, formatDate, statusTone, onRetry, onClear }: Props) {
  const tone = statusTone(run.status);
  const inProgress = run.status === "RUNNING" || run.status === "QUEUED";
  const steps = flowSteps(run);
  const headline = run.status_label || run.status;
  const detail = run.stage_label || run.current_stage;
  const files = Object.entries(run.files_progress || {}).filter(([name]) => name !== "_meta");

  return (
    <div className={`ingest-run status-block tone-${tone}${inProgress ? " is-live" : ""}`}>
      <div className="ingest-run-banner">
        <div className="ingest-run-banner-main">
          {inProgress ? <span className="ingest-run-spinner" aria-hidden /> : null}
          <div>
            <p className={`ingest-run-status status-pill ${tone}`}>{headline}</p>
            {detail && detail !== headline ? (
              <p className="ingest-run-detail">{detail}</p>
            ) : inProgress ? (
              <p className="ingest-run-detail">Working on your documents…</p>
            ) : null}
          </div>
        </div>
        {inProgress ? (
          <div className="ingest-run-progress" aria-hidden>
            <span className="ingest-run-progress-bar" />
          </div>
        ) : null}
      </div>

      <ol className="ingest-run-flow" aria-label="Ingestion stages">
        {steps.map((step, index) => (
          <li key={step.id} className={`ingest-run-flow-step ${step.state}`}>
            <span className="ingest-run-flow-dot" aria-hidden />
            <span className="ingest-run-flow-label">{step.label}</span>
            {index < steps.length - 1 ? <span className="ingest-run-flow-line" aria-hidden /> : null}
          </li>
        ))}
      </ol>

      <dl className="ingest-run-meta">
        <div>
          <dt>Case</dt>
          <dd>{run.case_id}</dd>
        </div>
        <div>
          <dt>Updated</dt>
          <dd>{formatDate(run.updated_at)}</dd>
        </div>
        <div className="ingest-run-meta-wide">
          <dt>Run</dt>
          <dd className="mono">{run.run_id}</dd>
        </div>
      </dl>

      {run.error_message ? <p className="text-danger ingest-run-error">{run.error_message}</p> : null}

      {files.length > 0 ? (
        <ul className="ingest-run-files">
          {files.map(([fileName, progress]) => {
            const state = fileRowState(progress, inProgress);
            const label =
              progress.stage_label || progress.stage || progress.status_label || "Pending";
            return (
              <li key={fileName} className={`ingest-run-file ${state}`}>
                <span className="ingest-run-file-mark" aria-hidden>
                  {state === "active" ? (
                    <span className="ingest-run-spinner sm" />
                  ) : state === "done" ? (
                    "✓"
                  ) : (
                    "·"
                  )}
                </span>
                <strong className="ingest-run-file-name">{fileName}</strong>
                <span className="ingest-run-file-stage">{label}</span>
              </li>
            );
          })}
        </ul>
      ) : null}

      <div className="action-row">
        {run.status === "FAILED" ? (
          <button className="btn btn-danger btn-sm" type="button" onClick={onRetry}>
            Retry current phase
          </button>
        ) : null}
        <button className="btn btn-ghost btn-sm" type="button" onClick={onClear}>
          Clear run context
        </button>
      </div>
    </div>
  );
}
