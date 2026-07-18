import { useEffect, useMemo, useState } from "react";
import { Link, useNavigate, useParams } from "react-router-dom";
import aegisBrandImage from "../../assets/aegis-brand.png";
import {
  DEMO_SCENARIOS,
  getScenarioById,
  type BriefingFindingVisual,
  type DemoScenario,
  type ScenarioDocument,
} from "../../data/scenarios";
import { getHeroSlide } from "../../data/scenarioHeroGraphs";
import { AssistantIcon } from "../assistant/icons";
import { DocumentPreviewModal } from "./DocumentPreviewModal";
import { ScenarioHeroGraph } from "./ScenarioHeroGraph";

const APP_TITLE = "CLARA — Crime Lifecycle Analytics and Reasoning Assistant";

function docsByNames(scenario: DemoScenario, names?: string[]): ScenarioDocument[] {
  if (!names?.length) return [];
  return names
    .map((name) => scenario.documents.find((doc) => doc.name === name))
    .filter((doc): doc is ScenarioDocument => Boolean(doc));
}

function BriefingVisual({
  visual,
  scenarioId,
}: {
  visual: BriefingFindingVisual;
  scenarioId: string;
}) {
  if (visual.kind === "heroGraph") {
    const slide = getHeroSlide(scenarioId);
    if (!slide) return null;
    return (
      <div className="briefing-finding briefing-finding-graph hero-visual">
        <ScenarioHeroGraph slide={slide} className="hero-slide-svg briefing-hero-svg" />
      </div>
    );
  }

  if (visual.kind === "metricStrip") {
    return (
      <div className="briefing-finding briefing-metric-strip" role="list">
        {visual.items.map((item) => (
          <div key={item.label} className="briefing-metric" role="listitem">
            <strong className="mono">{item.value}</strong>
            <span>{item.label}</span>
          </div>
        ))}
      </div>
    );
  }

  if (visual.kind === "callout") {
    return (
      <aside className={`briefing-finding briefing-callout tone-${visual.tone}`}>
        <span className="briefing-callout-label">
          {visual.tone === "wow" ? "Finding" : visual.tone === "amber" ? "Gap" : "Note"}
        </span>
        <p>{visual.text}</p>
      </aside>
    );
  }

  if (visual.kind === "stepList") {
    return (
      <div className="briefing-finding briefing-steps">
        <h4>{visual.title}</h4>
        <ol>
          {visual.steps.map((step) => (
            <li key={step}>{step}</li>
          ))}
        </ol>
      </div>
    );
  }

  if (visual.kind === "aliasCollapse") {
    return (
      <div className="briefing-finding briefing-aliases">
        <div className="briefing-alias-list">
          {visual.aliases.map((alias) => (
            <span key={alias} className="briefing-alias-chip mono">
              {alias}
            </span>
          ))}
        </div>
        <div className="briefing-alias-arrow" aria-hidden>
          →
        </div>
        <div className="briefing-alias-resolved">
          <span className="briefing-callout-label">Resolved</span>
          <strong>{visual.resolvedAs}</strong>
        </div>
      </div>
    );
  }

  if (visual.kind === "surgeBars") {
    const max = Math.max(...visual.weeks.map((week) => week.count), 1);
    return (
      <div className="briefing-finding briefing-surge-bars" role="img" aria-label="Weekly FIR counts">
        {visual.weeks.map((week) => (
          <div key={week.label} className="briefing-surge-col">
            <div className="briefing-surge-bar-track">
              <div
                className="briefing-surge-bar"
                style={{ height: `${Math.round((week.count / max) * 100)}%` }}
              />
            </div>
            <strong className="mono">{week.count}</strong>
            <span>{week.label}</span>
          </div>
        ))}
      </div>
    );
  }

  return null;
}

function DocChips({
  docs,
  onOpen,
}: {
  docs: ScenarioDocument[];
  onOpen: (name: string) => void;
}) {
  if (docs.length === 0) return null;
  return (
    <div className="briefing-doc-chips">
      {docs.map((doc) => (
        <button
          key={doc.name}
          type="button"
          className="briefing-doc-chip"
          onClick={() => onOpen(doc.name)}
        >
          <span className="briefing-doc-kind">{doc.fileType.toUpperCase()}</span>
          <span>{doc.label}</span>
          <AssistantIcon name="document" className="briefing-doc-chip-icon" />
        </button>
      ))}
    </div>
  );
}

export function ScenariosPage() {
  const { scenarioId: routeId } = useParams<{ scenarioId?: string }>();
  const navigate = useNavigate();
  const scenario = useMemo(() => {
    if (routeId) {
      return getScenarioById(routeId) ?? DEMO_SCENARIOS[0];
    }
    return DEMO_SCENARIOS[0];
  }, [routeId]);

  const [previewName, setPreviewName] = useState<string | null>(null);
  const previewOpen = previewName != null;
  const heroSlide = getHeroSlide(scenario.id);

  useEffect(() => {
    if (!routeId || !getScenarioById(routeId)) {
      navigate(`/scenarios/${DEMO_SCENARIOS[0].id}`, { replace: true });
    }
  }, [routeId, navigate]);

  useEffect(() => {
    setPreviewName(null);
  }, [scenario.id]);

  function selectScenario(id: string) {
    navigate(`/scenarios/${id}`);
  }

  function openDoc(name: string) {
    setPreviewName(name);
  }

  const { briefing } = scenario;
  const scenarioIndex = DEMO_SCENARIOS.findIndex((item) => item.id === scenario.id);

  return (
    <div className={`briefing-page accent-${briefing.accent}`}>
      <header className="briefing-topbar">
        <Link to="/" className="briefing-back">
          <AssistantIcon name="chevron-left" />
          <img src={aegisBrandImage} alt={APP_TITLE} className="briefing-brand" />
        </Link>
        <div className="briefing-topbar-title">
          <span className="hero-badge-dot" />
          <span>Scenario briefings</span>
        </div>
        <button
          type="button"
          className="btn btn-ghost"
          onClick={() => navigate(`/assistant?scenario=${scenario.id}`)}
        >
          Assistant
          <AssistantIcon name="chevron-right" />
        </button>
      </header>

      <div className="briefing-shell">
        <nav className="briefing-rail" aria-label="Demo scenarios">
          {DEMO_SCENARIOS.map((item, index) => (
            <button
              key={item.id}
              type="button"
              className={`briefing-rail-item${item.id === scenario.id ? " active" : ""}`}
              onClick={() => selectScenario(item.id)}
              aria-current={item.id === scenario.id ? "page" : undefined}
            >
              <span className="briefing-rail-index mono">{String(index + 1).padStart(2, "0")}</span>
              <span className="briefing-rail-copy">
                <strong>{item.shortTitle}</strong>
                <span>{item.briefing.primaryWow}</span>
              </span>
            </button>
          ))}
        </nav>

        <main className="briefing-main" key={scenario.id}>
          <section className="briefing-hero">
            <div className="briefing-hero-meta">
              <span className="briefing-kicker mono">
                Scenario {String(scenarioIndex + 1).padStart(2, "0")} / 04 · {scenario.crimeNo}
              </span>
              <h1>{scenario.shortTitle}</h1>
              <p className="briefing-hero-sub">
                <span>{briefing.persona}</span>
                <span className="briefing-dot" aria-hidden>
                  ·
                </span>
                <span>{briefing.victimLoss}</span>
              </p>
              <p className="briefing-wow">{briefing.primaryWow}</p>
              <p className="briefing-hook">{briefing.hook}</p>
              <div className="briefing-metric-strip briefing-hero-metrics" role="list">
                {briefing.metrics.map((metric) => (
                  <div key={metric.label} className="briefing-metric" role="listitem">
                    <strong className="mono">{metric.value}</strong>
                    <span>{metric.label}</span>
                  </div>
                ))}
              </div>
            </div>
            {heroSlide ? (
              <div className="briefing-hero-graph hero-visual">
                <ScenarioHeroGraph slide={heroSlide} className="hero-slide-svg briefing-hero-svg" />
              </div>
            ) : null}
          </section>

          <div className="briefing-chapters">
            {briefing.chapters.map((chapter, index) => (
              <article
                key={chapter.id}
                className="briefing-chapter"
                style={{ animationDelay: `${index * 40}ms` }}
              >
                <header className="briefing-chapter-head">
                  <span className="briefing-chapter-index mono">{String(index + 1).padStart(2, "0")}</span>
                  <h2>{chapter.title}</h2>
                </header>
                <p className="briefing-chapter-body">{chapter.body}</p>
                {chapter.visual ? (
                  <BriefingVisual visual={chapter.visual} scenarioId={scenario.id} />
                ) : null}
                <DocChips docs={docsByNames(scenario, chapter.documentNames)} onOpen={openDoc} />
              </article>
            ))}
          </div>

          <section className="briefing-casefile">
            <header className="briefing-casefile-head">
              <h2>Case file</h2>
              <p className="muted">Source documents for this demo — preview only; not shown as page text.</p>
            </header>
            <DocChips docs={scenario.documents} onOpen={openDoc} />
          </section>

          <footer className="briefing-footer">
            <button
              type="button"
              className="hero-cta"
              onClick={() => navigate(`/assistant?scenario=${scenario.id}`)}
            >
              <span>Open this scenario in Assistant</span>
              <AssistantIcon name="chevron-right" className="hero-cta-arrow" />
            </button>
          </footer>
        </main>
      </div>

      <DocumentPreviewModal
        open={previewOpen}
        documents={scenario.documents}
        activeName={previewName}
        scenarioTitle={scenario.shortTitle}
        onSelect={setPreviewName}
        onClose={() => setPreviewName(null)}
      />
    </div>
  );
}
