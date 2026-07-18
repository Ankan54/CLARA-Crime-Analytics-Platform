import { Link } from "react-router-dom";
import { DEMO_SCENARIOS } from "../../data/scenarios";
import { getHeroSlide } from "../../data/scenarioHeroGraphs";
import { ScenarioHeroGraph } from "../scenarios/ScenarioHeroGraph";

export function OverviewScenarioTiles() {
  return (
    <section className="overview-section" aria-labelledby="overview-uncover-title">
      <header className="overview-section-head overview-section-head-row">
        <div>
          <h3 id="overview-uncover-title">What you can uncover</h3>
          <p className="muted">Four demo journeys planted in the historical + live data.</p>
        </div>
        <Link to="/scenarios" className="overview-explore-all">
          Explore all scenarios →
        </Link>
      </header>
      <div className="overview-scenario-grid">
        {DEMO_SCENARIOS.map((scenario) => {
          const slide = getHeroSlide(scenario.id);
          return (
            <article key={scenario.id} className={`card overview-scenario-tile accent-${scenario.briefing.accent}`}>
              {slide ? (
                <div className="overview-scenario-graph hero-visual">
                  <ScenarioHeroGraph slide={slide} className="hero-slide-svg overview-tile-svg" />
                </div>
              ) : null}
              <div className="overview-scenario-copy">
                <h4>{scenario.shortTitle}</h4>
                <p>{scenario.briefing.primaryWow}</p>
                <Link to={`/scenarios/${scenario.id}`} className="overview-pipeline-link">
                  Read briefing →
                </Link>
              </div>
            </article>
          );
        })}
      </div>
    </section>
  );
}
