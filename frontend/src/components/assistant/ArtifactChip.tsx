import type { AssistantArtifact } from "../../lib/assistantTypes";
import { AssistantIcon, type AssistantIconName } from "./icons";

function iconFor(artifact: AssistantArtifact): AssistantIconName {
  if (artifact.kind === "graph") return "graph";
  if (artifact.kind === "table") return "table";
  return "document";
}

function metaFor(artifact: AssistantArtifact): string {
  if (artifact.kind === "graph") {
    return `${artifact.nodes.length} nodes · ${artifact.links.length} rels`;
  }
  if (artifact.kind === "table") {
    return `${artifact.rows.length} rows`;
  }
  return artifact.format.toUpperCase();
}

interface ArtifactChipProps {
  artifact: AssistantArtifact;
  onOpen: (artifact: AssistantArtifact) => void;
  active?: boolean;
}

/** Clickable chip representing one artifact produced by a turn; opens the right-side drawer. */
export function ArtifactChip({ artifact, onOpen, active }: ArtifactChipProps) {
  return (
    <button
      type="button"
      className={`artifact-chip${active ? " active" : ""}`}
      onClick={() => onOpen(artifact)}
    >
      <AssistantIcon name={iconFor(artifact)} />
      <span className="artifact-chip-body">
        <strong>{artifact.title}</strong>
        <span className="artifact-chip-meta">{metaFor(artifact)}</span>
      </span>
    </button>
  );
}
