import { Link } from "react-router-dom";

function CrimeModelTeaser() {
  return (
    <svg
      className="overview-crime-model-svg"
      viewBox="0 0 280 140"
      role="img"
      aria-label="Simplified crime model: Case, Person, Account, and Device connected by Mentions, Owns, and Transacted-with"
    >
      <line className="overview-cm-edge" x1="70" y1="40" x2="140" y2="70" />
      <line className="overview-cm-edge" x1="70" y1="100" x2="140" y2="70" />
      <line className="overview-cm-edge" x1="140" y1="70" x2="220" y2="40" />
      <line className="overview-cm-edge" x1="140" y1="70" x2="220" y2="100" />
      <circle className="overview-cm-node" cx="70" cy="40" r="18" />
      <circle className="overview-cm-node hub" cx="140" cy="70" r="22" />
      <circle className="overview-cm-node" cx="70" cy="100" r="18" />
      <circle className="overview-cm-node" cx="220" cy="40" r="18" />
      <circle className="overview-cm-node" cx="220" cy="100" r="18" />
      <text x="70" y="44" textAnchor="middle" className="overview-cm-label">
        Person
      </text>
      <text x="140" y="74" textAnchor="middle" className="overview-cm-label">
        Case
      </text>
      <text x="70" y="104" textAnchor="middle" className="overview-cm-label">
        Device
      </text>
      <text x="220" y="44" textAnchor="middle" className="overview-cm-label">
        Account
      </text>
      <text x="220" y="104" textAnchor="middle" className="overview-cm-label">
        UPI
      </text>
      <text x="100" y="52" className="overview-cm-edge-label">
        MENTIONS
      </text>
      <text x="168" y="48" className="overview-cm-edge-label">
        OWNS
      </text>
      <text x="155" y="98" className="overview-cm-edge-label">
        TXN
      </text>
    </svg>
  );
}

export function OverviewControlsStrip() {
  return (
    <section className="overview-section" aria-labelledby="overview-controls-title">
      <header className="overview-section-head">
        <h3 id="overview-controls-title">Controls that keep matches honest</h3>
        <p className="muted">Admin is the control room — not a day-to-day investigation step.</p>
      </header>
      <div className="overview-controls-grid">
        <article className="card overview-control-card">
          <div className="overview-control-visual">
            <CrimeModelTeaser />
          </div>
          <div className="overview-control-copy">
            <h4>
              Crime model <span className="muted">(ontology)</span>
            </h4>
            <p>
              The rulebook of what the system can extract and how those things may connect — so every
              case uses the same map. Document blueprints for FIR, IR, and evidence live here too.
            </p>
            <Link to="/admin" className="overview-pipeline-link">
              Open the full map →
            </Link>
          </div>
        </article>

        <article className="card overview-control-card">
          <div className="overview-control-visual overview-match-bar" aria-hidden>
            <span className="overview-match-end">Looser</span>
            <div className="overview-match-track">
              <span className="overview-match-thumb" />
            </div>
            <span className="overview-match-end">Stricter</span>
            <p className="overview-match-caption muted">Fewer same-person alerts →</p>
          </div>
          <div className="overview-control-copy">
            <h4>
              Match bar <span className="muted">(threshold)</span>
            </h4>
            <p>
              How similar two names must look before we flag “might be the same person.” You still
              decide every merge — the bar only controls what gets suggested.
            </p>
            <Link to="/admin" className="overview-pipeline-link">
              Adjust match bar →
            </Link>
          </div>
        </article>
      </div>
    </section>
  );
}
