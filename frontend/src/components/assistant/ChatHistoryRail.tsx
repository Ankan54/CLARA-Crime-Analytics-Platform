import type { AssistantSession } from "../../lib/assistantTypes";
import { AssistantIcon } from "./icons";

interface ChatHistoryRailProps {
  sessions: AssistantSession[];
  activeSessionId: string;
  collapsed: boolean;
  sessionsLabel: string;
  newChatLabel: string;
  onSelect: (id: string) => void;
  onNew: () => void;
  onDelete: (id: string) => void;
  onToggleCollapsed: () => void;
}

function relativeTime(iso: string): string {
  const then = new Date(iso).getTime();
  const diffMinutes = Math.round((Date.now() - then) / 60000);
  if (diffMinutes < 1) return "just now";
  if (diffMinutes < 60) return `${diffMinutes}m ago`;
  const diffHours = Math.round(diffMinutes / 60);
  if (diffHours < 24) return `${diffHours}h ago`;
  return new Date(iso).toLocaleDateString();
}

export function ChatHistoryRail({
  sessions,
  activeSessionId,
  collapsed,
  sessionsLabel,
  newChatLabel,
  onSelect,
  onNew,
  onDelete,
  onToggleCollapsed,
}: ChatHistoryRailProps) {
  return (
    <aside className={`chat-history-rail${collapsed ? " collapsed" : ""}`}>
      <div className="chat-history-rail-head">
        {!collapsed && <span className="kicker">{sessionsLabel}</span>}
        <button
          type="button"
          className="chat-history-toggle"
          onClick={onToggleCollapsed}
          title={collapsed ? "Expand history" : "Collapse history"}
        >
          <AssistantIcon name={collapsed ? "chevron-right" : "chevron-left"} />
        </button>
      </div>

      <button type="button" className="chat-history-new" onClick={onNew} title={newChatLabel}>
        <AssistantIcon name="plus" />
        {!collapsed && <span>{newChatLabel}</span>}
      </button>

      {!collapsed && (
        <div className="chat-history-list">
          {sessions.length === 0 && <p className="muted small">No sessions yet.</p>}
          {sessions.map((session) => (
            <div
              key={session.id}
              className={`chat-history-item${session.id === activeSessionId ? " active" : ""}`}
            >
              <button type="button" className="chat-history-item-select" onClick={() => onSelect(session.id)}>
                <AssistantIcon name="history" />
                <span className="chat-history-item-body">
                  <strong>{session.title}</strong>
                  <span className="muted small">{relativeTime(session.updatedAt)}</span>
                </span>
              </button>
              <button
                type="button"
                className="chat-history-item-delete"
                onClick={() => onDelete(session.id)}
                title="Delete session"
              >
                <AssistantIcon name="close" />
              </button>
            </div>
          ))}
        </div>
      )}
    </aside>
  );
}
