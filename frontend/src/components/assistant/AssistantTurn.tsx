import ReactMarkdown from "react-markdown";
import remarkGfm from "remark-gfm";
import rehypeHighlight from "rehype-highlight";
import aegisLogo from "../../assets/aegis-logo.png";
import type { AssistantAction, AssistantArtifact, AssistantMessage } from "../../lib/assistantTypes";
import { ReasoningTrail } from "./ReasoningTrail";
import { ArtifactChip } from "./ArtifactChip";
import { AssistantIcon, type AssistantIconName } from "./icons";
import { CodeBlock } from "./CodeBlock";

function actionIcon(action: AssistantAction): AssistantIconName {
  if (action.icon === "link") return "link";
  if (action.icon === "legal") return "legal";
  if (action.icon === "graph") return "graph";
  return "trend";
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
            <ReactMarkdown
              remarkPlugins={[remarkGfm]}
              rehypePlugins={[rehypeHighlight]}
              components={{
                code({ className, children, ...props }) {
                  const match = /language-(\w+)/.exec(className || "");
                  const text = String(children).replace(/\n$/, "");
                  const isBlock = Boolean(match) || text.includes("\n");
                  if (isBlock) {
                    return <CodeBlock code={text} language={match?.[1] || "text"} />;
                  }
                  return (
                    <code className={className} {...props}>
                      {children}
                    </code>
                  );
                },
              }}
            >
              {message.content}
            </ReactMarkdown>
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
          <div className="artifact-chip-row">
            {message.artifacts.map((artifact) => (
              <ArtifactChip
                key={artifact.id}
                artifact={artifact}
                onOpen={onOpenArtifact}
                active={activeArtifactId === artifact.id}
              />
            ))}
          </div>
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
          <div className="citation-panel">
            <div className="trace-title">Cited sources</div>
            {message.citations.map((citation, index) => (
              <button
                key={citation.id}
                className="citation-card"
                type="button"
                onClick={() => {
                  const artifact = message.artifacts?.find((item) => item.id === citation.documentArtifactId);
                  if (artifact) onOpenArtifact(artifact);
                  else if (citation.href) window.open(citation.href, "_blank", "noreferrer");
                }}
              >
                <span>
                  [{index + 1}] {citation.label}
                </span>
                <code>{citation.source}</code>
                {citation.snippet && <small>{citation.snippet}</small>}
              </button>
            ))}
          </div>
        )}

        {message.at && <time className="assistant-turn-time">{message.at}</time>}
      </div>
    </article>
  );
}
