import { Link } from "react-router-dom";
import { UserProfileMenu } from "../UserProfileMenu";
import { OverviewCapabilityStrip } from "./OverviewCapabilityStrip";
import { OverviewControlsStrip } from "./OverviewControlsStrip";
import { OverviewPipeline } from "./OverviewPipeline";
import { OverviewScenarioTiles } from "./OverviewScenarioTiles";

export function OverviewPage() {
  return (
    <div className="page-wrap overview-page">
      <header className="page-head overview-hero">
        <div className="page-head-copy">
          <p className="kicker">Platform overview</p>
          <h2>Connect cases. Follow money. Build charges.</h2>
          <p className="page-subtitle">
            Query your case records, find similar FIRs by modus operandi, and surface shared people,
            accounts, and devices across cases. Ask in plain language for timelines, money trails,
            and analysis reports — with sources you can check and a charge checklist for what&apos;s
            still missing.
          </p>
          <p className="overview-hero-explore">
            New here?{" "}
            <Link to="/scenarios">Explore the four demo scenarios</Link> before you ingest a case.
          </p>
        </div>
        <UserProfileMenu />
      </header>

      <OverviewPipeline />
      <OverviewCapabilityStrip />
      <OverviewControlsStrip />
      <OverviewScenarioTiles />

      <section className="overview-actions card panel" aria-labelledby="overview-actions-title">
        <header className="overview-actions-head">
          <h3 id="overview-actions-title">Ready to run a case</h3>
          <p className="muted">
            Configure the crime model and match bar in Admin, ingest your documents, then ask the
            assistant.
          </p>
        </header>
        <ol className="overview-actions-flow">
          <li>
            <Link to="/admin" className="btn overview-action-btn">
              <span className="overview-action-step mono">01</span>
              Configure in Admin
            </Link>
          </li>
          <li className="overview-actions-flow-arrow" aria-hidden>
            →
          </li>
          <li>
            <Link to="/ingest" className="btn overview-action-btn">
              <span className="overview-action-step mono">02</span>
              Start ingestion
            </Link>
          </li>
          <li className="overview-actions-flow-arrow" aria-hidden>
            →
          </li>
          <li>
            <Link to="/assistant" className="btn overview-action-btn">
              <span className="overview-action-step mono">03</span>
              Open assistant
            </Link>
          </li>
        </ol>
      </section>
    </div>
  );
}
