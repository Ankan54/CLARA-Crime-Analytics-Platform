import { AssistantIcon, type AssistantIconName } from "../assistant/icons";

const CAPABILITIES: Array<{
  id: string;
  label: string;
  title: string;
  body: string;
  icon: AssistantIconName;
}> = [
  {
    id: "sql",
    label: "SQL",
    title: "Structured facts",
    body: "Counts, filters, and money trails across cases and accounts.",
    icon: "table",
  },
  {
    id: "graph",
    label: "Graph",
    title: "Hidden links",
    body: "Shared accounts, devices, and people that join otherwise separate FIRs.",
    icon: "graph",
  },
  {
    id: "vector",
    label: "Vector",
    title: "Same script",
    body: "Find similar modus operandi across districts — even when names differ.",
    icon: "document",
  },
  {
    id: "legal",
    label: "Legal",
    title: "Charge checklist",
    body: "Offence → elements → evidence → precedents. See what's still amber.",
    icon: "legal",
  },
];

export function OverviewCapabilityStrip() {
  return (
    <section className="overview-section" aria-labelledby="overview-memory-title">
      <header className="overview-section-head">
        <h3 id="overview-memory-title">How it remembers</h3>
        <p className="muted">Three stores plus a legal layer — one answer path.</p>
      </header>
      <div className="overview-capability-grid">
        {CAPABILITIES.map((item) => (
          <article key={item.id} className={`overview-capability card accent-${item.id}`}>
            <div className="overview-capability-head">
              <span className="overview-capability-icon" aria-hidden>
                <AssistantIcon name={item.icon} />
              </span>
              <span className="overview-capability-label mono">{item.label}</span>
            </div>
            <h4>{item.title}</h4>
            <p>{item.body}</p>
          </article>
        ))}
      </div>
    </section>
  );
}
