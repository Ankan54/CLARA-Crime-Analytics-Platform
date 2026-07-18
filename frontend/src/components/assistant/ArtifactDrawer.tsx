import type { AssistantArtifact } from "../../lib/assistantTypes";
import { AssistantIcon } from "./icons";
import { GraphArtifactView } from "./GraphArtifactView";
import { TableArtifactView } from "./TableArtifactView";
import { DocumentArtifactView } from "./DocumentArtifactView";

interface ArtifactDrawerProps {
  artifact: AssistantArtifact | null;
  onClose: () => void;
}

/** Right-side slide-over that previews whichever artifact chip was clicked. */
export function ArtifactDrawer({ artifact, onClose }: ArtifactDrawerProps) {
  return (
    <div className={`artifact-drawer${artifact ? " open" : ""}`} aria-hidden={!artifact}>
      {artifact && (
        <>
          <header className="artifact-drawer-head">
            <div>
              <span className="kicker">{artifact.kind === "graph" ? "Graph preview" : artifact.kind === "table" ? "Table" : "Document"}</span>
              <h3>{artifact.title}</h3>
            </div>
            <button type="button" className="artifact-drawer-close" onClick={onClose} title="Close">
              <AssistantIcon name="close" />
            </button>
          </header>
          <div className="artifact-drawer-body">
            {artifact.kind === "graph" && <GraphArtifactView artifact={artifact} />}
            {artifact.kind === "table" && <TableArtifactView artifact={artifact} />}
            {artifact.kind === "document" && <DocumentArtifactView artifact={artifact} />}
          </div>
        </>
      )}
    </div>
  );
}
