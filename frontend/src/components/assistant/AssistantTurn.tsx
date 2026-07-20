import { useEffect, useState } from "react";
import aegisLogo from "../../assets/aegis-logo.png";
import type {
  AssistantAction,
  AssistantArtifact,
  AssistantCitation,
  AssistantMessage,
} from "../../lib/assistantTypes";
import { ReasoningTrail } from "./ReasoningTrail";
import { ArtifactChip } from "./ArtifactChip";
import { AssistantIcon, type AssistantIconName } from "./icons";
import { Markdown } from "./Markdown";

function actionIcon(action: AssistantAction): AssistantIconName {
  if (action.icon === "link") return "link";
  if (action.icon === "legal") return "legal";
  if (action.icon === "graph") return "graph";
  return "trend";
}

/** Short chip label for a citation: the real filename from a Stratus/file href when there
 *  is one (e.g. "fir.txt"), otherwise the officer-facing label. */
function citationChipLabel(citation: AssistantCitation): string {
  if (citation.href) {
    try {
      const path = new URL(citation.href).pathname;
      const base = decodeURIComponent(path.split("/").filter(Boolean).pop() || "");
      if (base && /\.[a-z0-9]{2,5}$/i.test(base)) return base;
    } catch {
      /* relative/artifact URL -- fall through to the label */
    }
  }
  return citation.label;
}

interface ArtifactChipBlockProps {
  artifacts: AssistantArtifact[];
  onOpen: (artifact: AssistantArtifact) => void;
  activeArtifactId?: string | null;
  streaming: boolean;
}

/** Collapsible chip strip — open while the turn streams, collapsed once done. */
function ArtifactChipBlock({ artifacts, onOpen, activeArtifactId, streaming }: ArtifactChipBlockProps) {
  const [expanded, setExpanded] = useState(streaming);
  const [autoCollapsed, setAutoCollapsed] = useState(false);

  useEffect(() => {
    if (streaming) {
      setExpanded(true);
      return;
    }
    if (!autoCollapsed && artifacts.length > 0) {
      setExpanded(false);
      setAutoCollapsed(true);
    }
  }, [streaming, autoCollapsed, artifacts.length]);

  const count = artifacts.length;
  const label = `${count} artifact${count === 1 ? "" : "s"}`;

  return (
    <div className={`artifact-chip-block${expanded ? " expanded" : ""}`}>
      <button
        type="button"
        className="artifact-chip-block-toggle"
        onClick={() => setExpanded((current) => !current)}
        aria-expanded={expanded}
      >
        <AssistantIcon name="table" className="artifact-chip-block-icon" />
        <span className="artifact-chip-block-label">{label}</span>
        <AssistantIcon name="chevron-down" className="artifact-chip-block-chevron" />
      </button>
      {expanded && (
        <div className="artifact-chip-row">
          {artifacts.map((artifact) => (
            <ArtifactChip
              key={artifact.id}
              artifact={artifact}
              onOpen={onOpen}
              active={activeArtifactId === artifact.id}
            />
          ))}
        </div>
      )}
    </div>
  );
}

interface AssistantTurnProps {
  message: AssistantMessage;
  onOpenArtifact: (artifact: AssistantArtifact) => void;
  onAction: (action: AssistantAction) => void;
  onRetry?: () => void;
  activeArtifactId?: string | null;
  busy: boolean;
}

export function AssistantTurn({ message, onOpenArtifact, onAction, onRetry, activeArtifactId, busy }: AssistantTurnProps) {
  if (message.role === "user") {
    return (
      <article className="assistant-turn user">
        <div className="assistant-turn-bubble">
          <p>{message.content}</p>
        </div>
        {message.at && <time>{message.at}</time>}
      </article>
    );
  }

  const streaming = message.status === "streaming";

  return (
    <article className="assistant-turn assistant">
      <div className="assistant-turn-avatar" aria-hidden="true">
        <img src={aegisLogo} alt="" />
      </div>
      <div className="assistant-turn-body">
        {message.steps && message.steps.length > 0 && (
          <ReasoningTrail steps={message.steps} plan={message.plan} streaming={streaming} />
        )}

        {message.content && message.status !== "error" && (
          <div className={`assistant-answer${streaming ? " is-streaming" : ""}`}>
            <Markdown>{message.content}</Markdown>
            {streaming && <span className="assistant-caret" aria-hidden="true" />}
          </div>
        )}

        {!message.content && streaming && (!message.steps || message.steps.length === 0) && (
          <div className="thinking-loader" role="status" aria-label="Thinking">
            <span className="thinking-dot" />
            <span className="thinking-dot" />
            <span className="thinking-dot" />
            <span className="thinking-loader-label">Thinking…</span>
          </div>
        )}

        {message.status === "error" && (
          <div className="alert alert-danger">
            <p>{message.error || "Something went wrong."}</p>
            {onRetry && !busy && (
              <button className="btn-retry" onClick={onRetry}>Try again</button>
            )}
          </div>
        )}

        {message.artifacts && message.artifacts.length > 0 && (
          <ArtifactChipBlock
            artifacts={message.artifacts}
            onOpen={onOpenArtifact}
            activeArtifactId={activeArtifactId}
            streaming={streaming}
          />
        )}

        {message.actions && message.actions.length > 0 && (
          <div className="assistant-action-row">
            {message.actions.map((action) => (
              <button
                key={action.id}
                type="button"
                className="btn btn-ghost btn-sm assistant-action-button"
                onClick={() => onAction(action)}
                disabled={busy}
              >
                <AssistantIcon name={actionIcon(action)} />
                {action.label}
              </button>
            ))}
          </div>
        )}

        {message.citations && message.citations.length > 0 && (
          <div className="citation-chip-row">
            <span className="citation-chip-row-label">Sources</span>
            {message.citations.map((citation, index) => (
              <span className="citation-chip-wrap" key={citation.id}>
                <button
                  className="citation-chip"
                  type="button"
                  onClick={() => {
                    const artifact = message.artifacts?.find((item) => item.id === citation.documentArtifactId);
                    if (artifact) onOpenArtifact(artifact);
                    else if (citation.href) window.open(citation.href, "_blank", "noreferrer");
                  }}
                >
                  <AssistantIcon name="document" className="citation-chip-icon" />
                  <span className="citation-chip-index">{index + 1}</span>
                  <span className="citation-chip-name">{citationChipLabel(citation)}</span>
                </button>
                <span className="citation-chip-preview" role="tooltip">
                  <strong>{citation.label}</strong>
                  <code>{citation.source}</code>
                  {citation.snippet && <span className="citation-chip-snippet">{citation.snippet}</span>}
                </span>
              </span>
            ))}
          </div>
        )}

        {message.at && <time className="assistant-turn-time">{message.at}</time>}
      </div>
    </article>
  );
}
