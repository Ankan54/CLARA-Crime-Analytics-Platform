import { useEffect, useRef } from "react";
import type { KeyboardEvent } from "react";
import { AssistantIcon } from "./icons";

interface ChatComposerProps {
  value: string;
  onChange: (value: string) => void;
  onSend: () => void;
  onStop?: () => void;
  placeholder: string;
  busy: boolean;
}

/** Message composer: textarea + send, swapping to Stop while a turn is streaming.
 *
 * The mic button that used to sit here was a visual placeholder with no audio capture --
 * removed rather than left in, since a control that silently does nothing is worse than
 * an absent one. Voice input can reclaim this spot when it is actually wired to an STT
 * backend.
 */
export function ChatComposer({ value, onChange, onSend, onStop, placeholder, busy }: ChatComposerProps) {
  const textareaRef = useRef<HTMLTextAreaElement | null>(null);

  // Auto-grow with content (capped by the CSS max-height) instead of a fixed 1-row box
  // that forces long questions into an internal scrollbar.
  useEffect(() => {
    const el = textareaRef.current;
    if (!el) return;
    el.style.height = "auto";
    el.style.height = `${el.scrollHeight}px`;
  }, [value]);

  function handleKeyDown(event: KeyboardEvent<HTMLTextAreaElement>): void {
    if (event.key === "Enter" && !event.shiftKey) {
      event.preventDefault();
      if (value.trim() && !busy) {
        onSend();
      }
    }
  }

  return (
    <form
      className="assistant-composer"
      onSubmit={(event) => {
        event.preventDefault();
        if (value.trim() && !busy) onSend();
      }}
    >
      <textarea
        ref={textareaRef}
        className="composer-textarea"
        value={value}
        onChange={(event) => onChange(event.target.value)}
        onKeyDown={handleKeyDown}
        placeholder={placeholder}
        rows={1}
      />
      {busy && onStop ? (
        <button type="button" className="composer-stop" onClick={onStop} title="Stop generating">
          <span className="composer-stop-glyph" aria-hidden="true" />
          <span className="sr-only">Stop</span>
        </button>
      ) : (
        <button type="submit" className="composer-send" disabled={busy || !value.trim()} title="Send">
          <AssistantIcon name="send" />
        </button>
      )}
    </form>
  );
}
