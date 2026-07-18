import { useEffect, useRef, useState } from "react";
import type { KeyboardEvent } from "react";
import type { AssistantLanguage } from "../../lib/assistantTypes";
import { refineTranscript, startTranscription, type TranscriptionHandle } from "../../lib/sttClient";
import { useToast } from "../ToastProvider";
import { AssistantIcon } from "./icons";

interface ChatComposerProps {
  value: string;
  onChange: (value: string) => void;
  onSend: () => void;
  onStop?: () => void;
  placeholder: string;
  busy: boolean;
  language: AssistantLanguage;
}

type MicPhase = "idle" | "listening" | "refining";

/** Message composer: mic + textarea + send, swapping to Stop while a turn is streaming. */
export function ChatComposer({
  value,
  onChange,
  onSend,
  onStop,
  placeholder,
  busy,
  language,
}: ChatComposerProps) {
  const toast = useToast();
  const textareaRef = useRef<HTMLTextAreaElement | null>(null);
  const handleRef = useRef<TranscriptionHandle | null>(null);
  const [phase, setPhase] = useState<MicPhase>("idle");

  // Auto-grow with content (capped by the CSS max-height) instead of a fixed 1-row box
  // that forces long questions into an internal scrollbar.
  useEffect(() => {
    const el = textareaRef.current;
    if (!el) return;
    el.style.height = "auto";
    el.style.height = `${el.scrollHeight}px`;
  }, [value]);

  useEffect(() => () => {
    // Unmount: drop the mic without waiting for refine.
    void handleRef.current?.stop().catch(() => undefined);
    handleRef.current = null;
  }, []);

  function handleKeyDown(event: KeyboardEvent<HTMLTextAreaElement>): void {
    if (event.key === "Enter" && !event.shiftKey) {
      event.preventDefault();
      if (value.trim() && !busy && phase === "idle") {
        onSend();
      }
    }
  }

  async function handleMicClick(): Promise<void> {
    if (busy) return;

    if (phase === "listening") {
      const handle = handleRef.current;
      handleRef.current = null;
      setPhase("refining");
      try {
        const raw = (await handle?.stop())?.trim() ?? "";
        if (!raw) {
          setPhase("idle");
          return;
        }
        onChange(raw);
        try {
          const refined = await refineTranscript(raw, language);
          onChange(refined);
        } catch (refineErr) {
          // Raw transcript is already in the box — refine is best-effort.
          toast.error(refineErr instanceof Error ? refineErr.message : "Could not refine transcript.");
        }
      } catch (stopErr) {
        toast.error(stopErr instanceof Error ? stopErr.message : "Transcription failed.");
      } finally {
        setPhase("idle");
      }
      return;
    }

    if (phase !== "idle") return;

    try {
      const handle = await startTranscription(language, (partial) => {
        onChange(partial);
      });
      handleRef.current = handle;
      setPhase("listening");
    } catch (startErr) {
      const message =
        startErr instanceof Error && /Permission|NotAllowed/i.test(startErr.message)
          ? "Microphone permission denied."
          : startErr instanceof Error
            ? startErr.message
            : "Could not start microphone.";
      toast.error(message);
      setPhase("idle");
    }
  }

  const micDisabled = busy || phase === "refining";
  const micClass =
    phase === "listening" ? "composer-mic listening" : phase === "refining" ? "composer-mic refining" : "composer-mic";
  const micTitle =
    phase === "listening" ? "Stop recording" : phase === "refining" ? "Cleaning up transcript…" : "Voice input";

  return (
    <form
      className="assistant-composer"
      onSubmit={(event) => {
        event.preventDefault();
        if (value.trim() && !busy && phase === "idle") onSend();
      }}
    >
      <button
        type="button"
        className={micClass}
        onClick={() => void handleMicClick()}
        disabled={micDisabled}
        title={micTitle}
        aria-label={micTitle}
        aria-pressed={phase === "listening"}
      >
        {phase === "refining" ? (
          <span className="composer-mic-spinner" aria-hidden="true" />
        ) : (
          <AssistantIcon name="mic" />
        )}
      </button>
      <textarea
        ref={textareaRef}
        className="composer-textarea"
        value={value}
        onChange={(event) => onChange(event.target.value)}
        onKeyDown={handleKeyDown}
        placeholder={phase === "listening" ? "Listening…" : phase === "refining" ? "Cleaning up…" : placeholder}
        rows={1}
        disabled={phase === "refining"}
      />
      {busy && onStop ? (
        <button type="button" className="composer-stop" onClick={onStop} title="Stop generating" aria-label="Stop generating">
          <span className="composer-stop-glyph" aria-hidden="true" />
        </button>
      ) : (
        <button
          type="submit"
          className="composer-send"
          disabled={busy || phase !== "idle" || !value.trim()}
          title="Send"
        >
          <AssistantIcon name="send" />
        </button>
      )}
    </form>
  );
}
