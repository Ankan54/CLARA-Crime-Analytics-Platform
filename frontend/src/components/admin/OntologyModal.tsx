import { useEffect, useState } from "react";
import { getOntology, type OntologyResponse } from "../../lib/api";
import { useToast } from "../ToastProvider";
import { OntologyGraph } from "./OntologyGraph";

export function OntologyModal({ open, onClose }: { open: boolean; onClose: () => void }) {
  const { error: showError } = useToast();
  const [data, setData] = useState<OntologyResponse | null>(null);
  const [loading, setLoading] = useState(false);
  const [failed, setFailed] = useState(false);

  useEffect(() => {
    if (!open) {
      return;
    }
    let cancelled = false;
    setLoading(true);
    setFailed(false);
    void getOntology()
      .then((resp) => {
        if (!cancelled) {
          setData(resp);
        }
      })
      .catch((err: unknown) => {
        if (!cancelled) {
          setFailed(true);
          showError(err instanceof Error ? err.message : "Failed to load ontology.");
        }
      })
      .finally(() => {
        if (!cancelled) {
          setLoading(false);
        }
      });
    return () => {
      cancelled = true;
    };
  }, [open, showError]);

  useEffect(() => {
    if (!open) {
      return;
    }
    function onKey(event: KeyboardEvent) {
      if (event.key === "Escape") {
        onClose();
      }
    }
    window.addEventListener("keydown", onKey);
    const prev = document.body.style.overflow;
    document.body.style.overflow = "hidden";
    return () => {
      window.removeEventListener("keydown", onKey);
      document.body.style.overflow = prev;
    };
  }, [open, onClose]);

  if (!open) {
    return null;
  }

  const entityCount = data?.entities.length ?? 0;
  const relCount = data?.relationships.length ?? 0;

  return (
    <div className="ontology-modal-backdrop" role="presentation" onClick={onClose}>
      <div
        className="ontology-modal"
        role="dialog"
        aria-modal="true"
        aria-labelledby="ontology-modal-title"
        onClick={(event) => event.stopPropagation()}
      >
        <header className="ontology-modal-head">
          <div className="ontology-modal-title-block">
            <h3 id="ontology-modal-title">
              Ontology
              <span className="ontology-modal-title-sep">•</span>
              <span className="ontology-modal-subtitle">
                {data?.title ?? "Crime intelligence model"}
              </span>
            </h3>
            {!loading && !failed ? (
              <p className="ontology-modal-meta muted">
                {entityCount} {entityCount === 1 ? "entity" : "entities"}
                <span aria-hidden> • </span>
                {relCount} {relCount === 1 ? "relationship" : "relationships"}
              </p>
            ) : null}
          </div>
          <button type="button" className="btn btn-ghost btn-sm" onClick={onClose}>
            Close
          </button>
        </header>
        <div className="ontology-modal-body">
          {loading ? <p className="muted ontology-modal-status">Loading ontology…</p> : null}
          {!loading && !failed && data && data.entities.length === 0 ? (
            <p className="muted ontology-modal-status">No active schema relationships found.</p>
          ) : null}
          {!loading && !failed && data && data.entities.length > 0 ? (
            <OntologyGraph entities={data.entities} relationships={data.relationships} />
          ) : null}
        </div>
      </div>
    </div>
  );
}
