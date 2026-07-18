import { useState } from "react";
import type { ScenarioPrompt } from "../../data/scenarios";
import { AssistantIcon } from "./icons";

interface SuggestedPromptsProps {
  prompts: ScenarioPrompt[];
  onSelect: (prompt: ScenarioPrompt) => void;
  title: string;
  disabled?: boolean;
}

/** Collapsible strip of the scenario's headline questions, shown above the composer. */
export function SuggestedPrompts({ prompts, onSelect, title, disabled }: SuggestedPromptsProps) {
  const [expanded, setExpanded] = useState(true);

  if (prompts.length === 0) {
    return null;
  }

  return (
    <div className={`suggested-prompts${expanded ? " expanded" : ""}`}>
      <button
        type="button"
        className="suggested-prompts-toggle"
        onClick={() => setExpanded((current) => !current)}
        aria-expanded={expanded}
      >
        <span>{title}</span>
        <AssistantIcon name="chevron-down" className="suggested-prompts-chevron" />
      </button>
      {expanded && (
        <div className="chip-wrap">
          {prompts.map((prompt) => (
            <button
              key={prompt.id}
              type="button"
              className="chip-button"
              disabled={disabled}
              onClick={() => onSelect(prompt)}
            >
              {prompt.label}
            </button>
          ))}
        </div>
      )}
    </div>
  );
}
