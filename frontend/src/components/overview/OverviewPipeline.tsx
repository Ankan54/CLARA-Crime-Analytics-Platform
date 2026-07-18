import { Link } from "react-router-dom";

type PipelineStage = {
  id: string;
  title: string;
  body: string;
  to?: string;
  cta?: string;
};

const STAGES: PipelineStage[] = [
  {
    id: "explore",
    title: "Explore",
    body: "Read the demo stories; preview FIR, IR, and evidence.",
    to: "/scenarios",
    cta: "Explore scenarios",
  },
  {
    id: "ingest",
    title: "Ingest",
    body: "Upload documents; confirm possible same-person matches before anything loads.",
    to: "/ingest",
    cta: "Open ingest",
  },
  {
    id: "merge",
    title: "Merge",
    body: "Live case joins historical records, links, and narratives.",
  },
  {
    id: "ask",
    title: "Ask",
    body: "Ask in plain language; see the reasoning trail and sources.",
    to: "/assistant",
    cta: "Open assistant",
  },
  {
    id: "act",
    title: "Act",
    body: "Charge checklist — what's proven, what's amber, what's missing.",
    to: "/assistant",
    cta: "Ask legal gaps",
  },
];

export function OverviewPipeline() {
  return (
    <section className="overview-section" aria-labelledby="overview-pipeline-title">
      <header className="overview-section-head">
        <h3 id="overview-pipeline-title">Investigation pipeline</h3>
        <p className="muted">How a case moves through the workspace.</p>
      </header>
      <ol className="overview-pipeline">
        {STAGES.map((stage, index) => (
          <li
            key={stage.id}
            className="overview-pipeline-node"
            style={{ animationDelay: `${index * 40}ms` }}
          >
            <span className="overview-pipeline-index mono">{String(index + 1).padStart(2, "0")}</span>
            <h4>{stage.title}</h4>
            <p>{stage.body}</p>
            {stage.to && stage.cta ? (
              <Link to={stage.to} className="overview-pipeline-link">
                {stage.cta} →
              </Link>
            ) : null}
            {index < STAGES.length - 1 ? (
              <span className="overview-pipeline-arrow" aria-hidden>
                →
              </span>
            ) : null}
          </li>
        ))}
      </ol>
    </section>
  );
}
