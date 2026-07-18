import { useEffect, useMemo, useState } from "react";
import {
  Link,
  Navigate,
  NavLink,
  Outlet,
  Route,
  Routes,
  useLocation,
  useNavigate,
} from "react-router-dom";
import { FIXED_DEMO_USER } from "./config/demoUser";
import { DEMO_SCENARIOS, type DemoScenario } from "./data/scenarios";
import aegisBrandImage from "./assets/aegis-brand.png";
import aegisLogo from "./assets/aegis-logo.png";
import { UserProfileMenu } from "./components/UserProfileMenu";
import { AssistantPage } from "./components/assistant/AssistantPage";
import { AssistantIcon } from "./components/assistant/icons";
import {
  activateSchemaVersion,
  buildPipelineWebSocketUrl,
  getFindings,
  getPipelineStatus,
  getReviewQueue,
  getSchemaDetail,
  getSchemaVersions,
  getThreshold,
  listActiveSchemas,
  listCases,
  prepareScenario,
  proceedRun,
  resolveReviewItem,
  retryRun,
  startProcess,
  updateThreshold,
  uploadDocuments,
  type ActiveSchemaSummary,
  type CaseSummary,
  type FindingsResponse,
  type PipelineRun,
  type ReviewQueueItem,
  type SchemaDetailResponse,
  type SchemaVersionSummary,
  type UploadFileEntry,
  type UploadFileType,
} from "./lib/api";

const TERMINAL_PIPELINE_STATUSES = new Set([
  "COMPLETED",
  "COMPLETED_WITH_REVIEW_PENDING",
  "FAILED",
]);
// REST fallback poll for pipeline status -- the WebSocket carries most updates via
// server push, so this only needs to catch a missed/dropped socket, not drive the UI.
const STATUS_POLL_INTERVAL_MS = 12000;
const CURRENT_RUN_STORAGE_KEY = "crime-analytics-assistant.current-run-id";

type DraftFile = {
  id: string;
  file: File;
  fileType: UploadFileType;
};

function formatFileSize(bytes: number): string {
  if (bytes < 1024 * 1024) {
    return `${(bytes / 1024).toFixed(1)} KB`;
  }
  return `${(bytes / (1024 * 1024)).toFixed(2)} MB`;
}

function formatDate(value?: string): string {
  if (!value) {
    return "N/A";
  }
  const parsed = new Date(value);
  if (Number.isNaN(parsed.getTime())) {
    return value;
  }
  return parsed.toLocaleString();
}

function statusTone(status?: string): "neutral" | "ok" | "warn" | "danger" {
  if (!status) {
    return "neutral";
  }
  if (status === "REVIEW_PENDING") {
    return "warn";
  }
  if (status === "COMPLETED" || status === "COMPLETED_WITH_REVIEW_PENDING") {
    return "ok";
  }
  if (status === "FAILED") {
    return "danger";
  }
  return "neutral";
}

function makeId(prefix: string): string {
  if (typeof crypto !== "undefined" && typeof crypto.randomUUID === "function") {
    return `${prefix}-${crypto.randomUUID()}`;
  }
  return `${prefix}-${Date.now()}-${Math.random().toString(16).slice(2)}`;
}

type LandingGraphNodeTone = "money" | "hub" | "alias" | "leader";
type LandingGraphEdgeTone = "money" | "control" | "alias";

type LandingGraphNode = {
  id: string;
  x: number;
  y: number;
  r: number;
  tone: LandingGraphNodeTone;
  pulseClass?: string;
  halo?: boolean;
  fill?: string;
};

type LandingGraphEdge = {
  from: string;
  to: string;
  tone: LandingGraphEdgeTone;
};

type LandingGraphText = {
  x: number;
  y: number;
  value: string;
  className: string;
  anchor?: "start" | "middle" | "end";
};

type LandingHeroSlide = {
  id: string;
  title: string;
  ariaLabel: string;
  caption: string;
  nodes: LandingGraphNode[];
  edges: LandingGraphEdge[];
  texts: LandingGraphText[];
};

const LANDING_HERO_SLIDES: LandingHeroSlide[] = [
  {
    id: "digital-arrest",
    title: "Digital Arrest",
    ariaLabel:
      "Digital arrest ring view where three district FIRs converge into one HDFC hub account and resolve to one ring leader with aliases.",
    caption:
      "FIRs from three districts resolve to one HDFC hub account holding Rs 54L, controlled by a single accused operating under 3 aliases.",
    nodes: [
      { id: "mysuru", x: 66, y: 64, r: 15, tone: "money" },
      { id: "mangaluru", x: 50, y: 190, r: 15, tone: "money", pulseClass: "n2" },
      { id: "hubballi", x: 66, y: 316, r: 15, tone: "money", pulseClass: "n3" },
      { id: "hub", x: 196, y: 190, r: 22, tone: "hub", pulseClass: "n4" },
      { id: "aliasA", x: 430, y: 92, r: 14, tone: "alias", pulseClass: "n5" },
      { id: "aliasB", x: 430, y: 288, r: 14, tone: "alias", pulseClass: "n6" },
      { id: "leader", x: 352, y: 190, r: 30, tone: "leader", halo: true },
    ],
    edges: [
      { from: "mysuru", to: "hub", tone: "money" },
      { from: "mangaluru", to: "hub", tone: "money" },
      { from: "hubballi", to: "hub", tone: "money" },
      { from: "hub", to: "leader", tone: "control" },
      { from: "aliasA", to: "leader", tone: "alias" },
      { from: "aliasB", to: "leader", tone: "alias" },
    ],
    texts: [
      { x: 66, y: 36, value: "MYSURU", className: "node-label" },
      { x: 66, y: 92, value: "Rs 21L", className: "node-label amount-sm" },
      { x: 50, y: 162, value: "MANGALURU", className: "node-label" },
      { x: 50, y: 220, value: "Rs 18L", className: "node-label amount-sm" },
      { x: 66, y: 288, value: "HUBBALLI", className: "node-label" },
      { x: 66, y: 344, value: "Rs 15L", className: "node-label amount-sm" },
      { x: 196, y: 150, value: "Rs 54L", className: "amount" },
      { x: 196, y: 226, value: "AGGREGATION HUB", className: "node-label hub" },
      { x: 196, y: 239, value: "HDFC ..0001", className: "node-label" },
      { x: 352, y: 140, value: "RING LEADER", className: "node-label lead" },
      { x: 352, y: 230, value: "VICTOR HALE", className: "node-label name" },
      { x: 352, y: 243, value: "3 aliases - 3 districts", className: "node-label" },
      { x: 424, y: 70, value: "V. Hale", className: "node-label alias" },
      { x: 424, y: 316, value: "Viktor Hall", className: "node-label alias" },
    ],
  },
  {
    id: "many-names",
    title: "Many Names, One Man",
    ariaLabel:
      "Alias-resolution view where multiple identity variants collapse to one repeat offender linked by shared phone, UPI, and IMEI.",
    caption:
      "Alias variants and identifiers collapse into one repeat offender, showing escalation from smaller frauds to a Rs 15L investment scam.",
    nodes: [
      { id: "alias1", x: 86, y: 74, r: 14, tone: "money" },
      { id: "alias2", x: 58, y: 166, r: 13, tone: "money", pulseClass: "n2" },
      { id: "alias3", x: 82, y: 268, r: 13, tone: "money", pulseClass: "n3" },
      { id: "alias4", x: 146, y: 330, r: 13, tone: "money", pulseClass: "n4" },
      { id: "identity", x: 218, y: 202, r: 22, tone: "hub", pulseClass: "n5" },
      { id: "offender", x: 348, y: 170, r: 30, tone: "leader", halo: true },
      { id: "imei", x: 430, y: 96, r: 14, tone: "alias", pulseClass: "n6" },
      { id: "upi", x: 430, y: 246, r: 14, tone: "alias" },
      { id: "phone", x: 364, y: 304, r: 12, tone: "alias" },
    ],
    edges: [
      { from: "alias1", to: "identity", tone: "money" },
      { from: "alias2", to: "identity", tone: "money" },
      { from: "alias3", to: "identity", tone: "money" },
      { from: "alias4", to: "identity", tone: "money" },
      { from: "identity", to: "offender", tone: "control" },
      { from: "imei", to: "offender", tone: "alias" },
      { from: "upi", to: "offender", tone: "alias" },
      { from: "phone", to: "offender", tone: "alias" },
    ],
    texts: [
      { x: 86, y: 50, value: "ALIAS 01", className: "node-label" },
      { x: 86, y: 99, value: "Imran S.", className: "node-label amount-sm" },
      { x: 58, y: 142, value: "ALIAS 02", className: "node-label" },
      { x: 58, y: 191, value: "Imraan S.", className: "node-label amount-sm" },
      { x: 82, y: 244, value: "ALIAS 03", className: "node-label" },
      { x: 82, y: 293, value: "I. Shaikh", className: "node-label amount-sm" },
      { x: 146, y: 306, value: "ALIAS 04", className: "node-label" },
      { x: 146, y: 354, value: "I. Shek", className: "node-label amount-sm" },
      { x: 218, y: 162, value: "4 to 1", className: "amount" },
      { x: 218, y: 239, value: "IDENTITY RESOLVED", className: "node-label hub" },
      { x: 218, y: 252, value: "IMEI + UPI + phone", className: "node-label" },
      { x: 348, y: 121, value: "KNOWN OFFENDER", className: "node-label lead" },
      { x: 348, y: 212, value: "IMRAN SHEIKH", className: "node-label name" },
      { x: 348, y: 226, value: "2024 to 2026 escalation", className: "node-label" },
      { x: 430, y: 74, value: "IMEI 3517..1234", className: "node-label alias" },
      { x: 430, y: 270, value: "UPI imran@axl", className: "node-label alias" },
      { x: 364, y: 329, value: "Phone 9611..", className: "node-label alias" },
    ],
  },
  {
    id: "follow-money",
    title: "Follow The Money",
    ariaLabel:
      "Money-trail view where victim loss moves through a bridge account and mule pool, with freezable funds and a bridge network highlighted.",
    caption:
      "Time-ordered layering highlights one bridge account across scam types and isolates Rs 6.2L that can still be frozen.",
    nodes: [
      { id: "victim", x: 54, y: 190, r: 15, tone: "money" },
      { id: "layer1", x: 132, y: 110, r: 13, tone: "money", pulseClass: "n2" },
      { id: "layer2", x: 132, y: 270, r: 13, tone: "money", pulseClass: "n3" },
      { id: "bridge", x: 216, y: 190, r: 22, tone: "hub", pulseClass: "n4" },
      { id: "mule1", x: 302, y: 94, r: 12, tone: "money", pulseClass: "n5" },
      { id: "mule2", x: 314, y: 190, r: 12, tone: "money", pulseClass: "n6" },
      { id: "mule3", x: 302, y: 286, r: 12, tone: "money" },
      { id: "operator", x: 390, y: 190, r: 30, tone: "leader", halo: true },
      { id: "cashout", x: 452, y: 98, r: 13, tone: "alias" },
      { id: "wallet", x: 452, y: 290, r: 13, tone: "alias" },
    ],
    edges: [
      { from: "victim", to: "layer1", tone: "money" },
      { from: "victim", to: "layer2", tone: "money" },
      { from: "layer1", to: "bridge", tone: "money" },
      { from: "layer2", to: "bridge", tone: "money" },
      { from: "bridge", to: "mule1", tone: "control" },
      { from: "bridge", to: "mule2", tone: "control" },
      { from: "bridge", to: "mule3", tone: "control" },
      { from: "mule2", to: "operator", tone: "control" },
      { from: "mule1", to: "cashout", tone: "alias" },
      { from: "mule3", to: "wallet", tone: "alias" },
      { from: "operator", to: "wallet", tone: "alias" },
    ],
    texts: [
      { x: 54, y: 164, value: "DHARWAD", className: "node-label" },
      { x: 54, y: 214, value: "Rs 28L LOSS", className: "node-label amount-sm" },
      { x: 216, y: 153, value: "BRIDGE", className: "amount" },
      { x: 216, y: 230, value: "A/C ..9001", className: "node-label hub" },
      { x: 216, y: 244, value: "cross-scam node", className: "node-label" },
      { x: 304, y: 168, value: "Rs 6.2L", className: "amount" },
      { x: 304, y: 183, value: "FREEZABLE NOW", className: "node-label lead" },
      { x: 390, y: 138, value: "HUB OPERATOR", className: "node-label lead" },
      { x: 390, y: 230, value: "MONEY RING", className: "node-label name" },
      { x: 390, y: 243, value: "11 mule accounts", className: "node-label" },
      { x: 452, y: 76, value: "Cash-out leg", className: "node-label alias" },
      { x: 452, y: 315, value: "USDT wallet", className: "node-label alias" },
    ],
  },
  {
    id: "surge",
    title: "The Surge",
    ariaLabel:
      "Surge-detection view where weekly FIR spikes converge into one organized task-scam ring with shared device and IP infrastructure.",
    caption:
      "A 21-day burst of FIRs collapses into one coordinated community, with shared device and IP infrastructure revealing the controller.",
    nodes: [
      { id: "wk1", x: 68, y: 86, r: 13, tone: "money" },
      { id: "wk2", x: 52, y: 190, r: 13, tone: "money", pulseClass: "n2" },
      { id: "wk3", x: 68, y: 294, r: 13, tone: "money", pulseClass: "n3" },
      { id: "cluster", x: 184, y: 190, r: 22, tone: "hub", pulseClass: "n4" },
      { id: "member1", x: 248, y: 118, r: 11, tone: "money", pulseClass: "n5" },
      { id: "member2", x: 276, y: 170, r: 11, tone: "money", pulseClass: "n6" },
      { id: "member3", x: 270, y: 236, r: 11, tone: "money" },
      { id: "member4", x: 236, y: 278, r: 11, tone: "money" },
      { id: "member5", x: 212, y: 124, r: 11, tone: "money" },
      { id: "controller", x: 350, y: 190, r: 30, tone: "leader", halo: true },
      { id: "device", x: 430, y: 108, r: 13, tone: "alias" },
      { id: "ip", x: 430, y: 272, r: 13, tone: "alias" },
    ],
    edges: [
      { from: "wk1", to: "cluster", tone: "money" },
      { from: "wk2", to: "cluster", tone: "money" },
      { from: "wk3", to: "cluster", tone: "money" },
      { from: "cluster", to: "member1", tone: "money" },
      { from: "cluster", to: "member2", tone: "money" },
      { from: "cluster", to: "member3", tone: "money" },
      { from: "cluster", to: "member4", tone: "money" },
      { from: "cluster", to: "member5", tone: "money" },
      { from: "member1", to: "controller", tone: "control" },
      { from: "member2", to: "controller", tone: "control" },
      { from: "member3", to: "controller", tone: "control" },
      { from: "member4", to: "controller", tone: "control" },
      { from: "member5", to: "controller", tone: "control" },
      { from: "cluster", to: "controller", tone: "control" },
      { from: "device", to: "controller", tone: "alias" },
      { from: "ip", to: "controller", tone: "alias" },
    ],
    texts: [
      { x: 68, y: 63, value: "WEEK 1", className: "node-label" },
      { x: 68, y: 110, value: "3 FIRs", className: "node-label amount-sm" },
      { x: 52, y: 167, value: "WEEK 2", className: "node-label" },
      { x: 52, y: 214, value: "7 FIRs", className: "node-label amount-sm" },
      { x: 68, y: 271, value: "WEEK 3", className: "node-label" },
      { x: 68, y: 317, value: "9 FIRs", className: "node-label amount-sm" },
      { x: 184, y: 152, value: "19 FIRs", className: "amount" },
      { x: 184, y: 229, value: "SURGE CLUSTER", className: "node-label hub" },
      { x: 184, y: 242, value: "last 21 days", className: "node-label" },
      { x: 350, y: 140, value: "RING CONTROLLER", className: "node-label lead" },
      { x: 350, y: 230, value: "TASK-SCAM CELL", className: "node-label name" },
      { x: 350, y: 243, value: "~7 operators", className: "node-label" },
      { x: 430, y: 84, value: "Device pool", className: "node-label alias" },
      { x: 430, y: 297, value: "IP 103.74.*", className: "node-label alias" },
      { x: 252, y: 307, value: "Community core", className: "node-label alias" },
    ],
  },
];

function nodeStrokeColor(tone: LandingGraphNodeTone): string {
  if (tone === "hub" || tone === "leader") {
    return "#f7c948";
  }
  if (tone === "alias") {
    return "#8b7cff";
  }
  return "#35e0ff";
}

function nodeStrokeWidth(tone: LandingGraphNodeTone): number {
  if (tone === "leader") {
    return 3;
  }
  if (tone === "hub") {
    return 2.4;
  }
  return 2;
}

function nodeFillColor(node: LandingGraphNode): string {
  if (node.fill) {
    return node.fill;
  }
  return node.tone === "leader" ? "#141003" : "#0b1020";
}

function LandingScenarioSlideshow() {
  const [activeSlideIndex, setActiveSlideIndex] = useState<number>(0);

  useEffect(() => {
    if (window.matchMedia("(prefers-reduced-motion: reduce)").matches) {
      return;
    }
    const timer = window.setInterval(() => {
      setActiveSlideIndex((currentIndex) => (currentIndex + 1) % LANDING_HERO_SLIDES.length);
    }, 15000);
    return () => {
      window.clearInterval(timer);
    };
  }, []);

  const activeSlide = LANDING_HERO_SLIDES[activeSlideIndex];
  const nodeLookup = useMemo(
    () => new Map(activeSlide.nodes.map((node) => [node.id, node])),
    [activeSlide],
  );

  return (
    <div className="hero-visual">
      <div className="hero-slide-head">
        <span className="hero-slide-kicker">
          Scenario {String(activeSlideIndex + 1).padStart(2, "0")} /{" "}
          {String(LANDING_HERO_SLIDES.length).padStart(2, "0")}
        </span>
        <strong>{activeSlide.title}</strong>
      </div>

      <svg
        key={activeSlide.id}
        className="hero-slide-svg"
        viewBox="0 0 480 380"
        role="img"
        aria-label={activeSlide.ariaLabel}
      >
        {activeSlide.edges.map((edge, index) => {
          const from = nodeLookup.get(edge.from);
          const to = nodeLookup.get(edge.to);
          if (!from || !to) {
            return null;
          }
          return (
            <line
              key={`${activeSlide.id}-edge-${edge.from}-${edge.to}-${index}`}
              className={`edge ${edge.tone}`}
              x1={from.x}
              y1={from.y}
              x2={to.x}
              y2={to.y}
            />
          );
        })}

        {activeSlide.nodes.map((node) => (
          <g key={`${activeSlide.id}-node-${node.id}`}>
            {node.halo && <circle className="leader-halo" cx={node.x} cy={node.y} r={node.r} />}
            <circle
              className={`dot${node.pulseClass ? ` ${node.pulseClass}` : ""}`}
              cx={node.x}
              cy={node.y}
              r={node.r}
              fill={nodeFillColor(node)}
              stroke={nodeStrokeColor(node.tone)}
              strokeWidth={nodeStrokeWidth(node.tone)}
            />
          </g>
        ))}

        {activeSlide.texts.map((text, index) => (
          <text
            key={`${activeSlide.id}-text-${index}`}
            className={text.className}
            x={text.x}
            y={text.y}
            textAnchor={text.anchor ?? "middle"}
          >
            {text.value}
          </text>
        ))}
      </svg>

      <p className="hero-caption">
        <span className="hero-caption-tag">Scenario</span>
        {activeSlide.caption}
      </p>

      <div className="hero-slide-dots" aria-label="Landing scenario slideshow">
        {LANDING_HERO_SLIDES.map((slide, index) => (
          <button
            key={slide.id}
            className={`hero-slide-dot${index === activeSlideIndex ? " active" : ""}`}
            type="button"
            onClick={() => setActiveSlideIndex(index)}
            aria-label={`Show ${slide.title}`}
            aria-pressed={index === activeSlideIndex}
          />
        ))}
      </div>
    </div>
  );
}

function App() {
  return (
    <Routes>
      <Route path="/" element={<LandingPage />} />
      <Route element={<ConsoleLayout />}>
        <Route path="/dashboard" element={<DashboardPage />} />
        <Route path="/ingest" element={<IngestPage />} />
        <Route path="/assistant" element={<AssistantPage />} />
        <Route path="/admin" element={<AdminPage />} />
      </Route>
      <Route path="*" element={<Navigate to="/" replace />} />
    </Routes>
  );
}

function LandingPage() {
  const navigate = useNavigate();

  return (
    <div className="landing-page">
      <div className="landing-inner">
        <div className="landing-copyblock">
          <span className="hero-badge">
            <span className="hero-badge-dot" />
            Karnataka State Police Datathon 2026 · prototype
          </span>
          <div className="hero-brand">
            <img
              className="hero-lockup-image"
              src={aegisBrandImage}
              alt="Aegis Crime Analytics Assistant"
            />
          </div>
          <p className="landing-copy">
            A single workspace for case document ingestion, entity-network links, and officer
            review, built on a multi-agent retrieval engine.
          </p>
          <div className="hero-actions">
            <button
              className="hero-cta"
              type="button"
              onClick={() => navigate("/dashboard")}
            >
              <span>Start analysis</span>
              <AssistantIcon name="chevron-right" className="hero-cta-arrow" />
            </button>
            <button
              className="btn btn-ghost btn-lg hero-cta-secondary"
              type="button"
              onClick={() => navigate("/ingest")}
            >
              Explore scenarios
            </button>
          </div>
          <div className="hero-stats">
            <div className="hero-stat">
              <strong>Search everything at once</strong>
              <span>Cases, suspects, evidence &amp; legal docs — one query</span>
            </div>
            <div className="hero-stat">
              <strong>Connects the dots automatically</strong>
              <span>Suspects, events &amp; entities linked across records</span>
            </div>
            <div className="hero-stat">
              <strong>Officers stay in control</strong>
              <span>Every AI finding reviewed before action is taken</span>
            </div>
          </div>
        </div>

        <LandingScenarioSlideshow />
      </div>

      <PoweredBy />
    </div>
  );
}

const TECH_STACK: Array<{ name: string; note: string; logo: string }> = [
  { name: "Zoho Catalyst", note: "Serverless · Stratus · QuickML", logo: "/logos/catalyst-logo.svg" },
  { name: "Pinecone", note: "Vector search", logo: "/logos/pinecone_new.svg" },
  { name: "Neo4j", note: "Entity graph", logo: "/logos/neo4j.svg" },
  { name: "LangGraph", note: "Agent orchestration", logo: "/logos/langgraph-logo.svg" },
  { name: "FastAPI", note: "Backend API", logo: "/logos/fastapi.svg" },
  { name: "React", note: "Console UI", logo: "/logos/react.svg" },
];

function PoweredBy() {
  return (
    <div className="powered-by">
      <span className="powered-by-label">Built on</span>
      <div className="powered-by-row">
        {TECH_STACK.map((tech) => (
          <div key={tech.name} className="tech-chip" title={tech.note}>
            <img src={tech.logo} alt="" aria-hidden loading="lazy" />
            <strong>{tech.name}</strong>
          </div>
        ))}
      </div>
      <p className="creator-tag">
        Created by <strong>Team Radiant Rangers</strong> — Ankan Bera
      </p>
    </div>
  );
}

const SIDEBAR_COLLAPSED_KEY = "aegis.sidebar.collapsed";

type NavIconName = "overview" | "ingest" | "assistant" | "admin";

/** Small stroke-icon set for the sidebar nav links, shown always but especially load-bearing when collapsed. */
function NavIcon({ name }: { name: NavIconName }) {
  const common = {
    width: 17,
    height: 17,
    viewBox: "0 0 24 24",
    fill: "none",
    stroke: "currentColor",
    strokeWidth: 1.8,
    strokeLinecap: "round" as const,
    strokeLinejoin: "round" as const,
  };
  if (name === "overview") {
    return (
      <svg {...common}>
        <rect x="3.5" y="3.5" width="7.5" height="7.5" rx="1.2" />
        <rect x="13" y="3.5" width="7.5" height="4.5" rx="1.2" />
        <rect x="13" y="10.5" width="7.5" height="10" rx="1.2" />
        <rect x="3.5" y="13.5" width="7.5" height="7" rx="1.2" />
      </svg>
    );
  }
  if (name === "ingest") {
    return (
      <svg {...common}>
        <path d="M12 13V4" />
        <polyline points="7.5 8.5 12 4 16.5 8.5" />
        <path d="M4 14v3a2 2 0 0 0 2 2h12a2 2 0 0 0 2-2v-3" />
      </svg>
    );
  }
  if (name === "assistant") {
    return (
      <svg {...common}>
        <path d="M4 5h16v11H9l-5 4z" />
        <line x1="8" y1="9" x2="16" y2="9" />
        <line x1="8" y1="12.5" x2="13" y2="12.5" />
      </svg>
    );
  }
  return (
    <svg {...common}>
      <path d="M12.22 2h-.44a2 2 0 0 0-2 2v.18a2 2 0 0 1-1 1.73l-.43.25a2 2 0 0 1-2 0l-.15-.08a2 2 0 0 0-2.73.73l-.22.38a2 2 0 0 0 .73 2.73l.15.1a2 2 0 0 1 1 1.72v.51a2 2 0 0 1-1 1.74l-.15.09a2 2 0 0 0-.73 2.73l.22.38a2 2 0 0 0 2.73.73l.15-.08a2 2 0 0 1 2 0l.43.25a2 2 0 0 1 1 1.73V20a2 2 0 0 0 2 2h.44a2 2 0 0 0 2-2v-.18a2 2 0 0 1 1-1.73l.43-.25a2 2 0 0 1 2 0l.15.08a2 2 0 0 0 2.73-.73l.22-.39a2 2 0 0 0-.73-2.73l-.15-.08a2 2 0 0 1-1-1.74v-.5a2 2 0 0 1 1-1.74l.15-.09a2 2 0 0 0 .73-2.73l-.22-.38a2 2 0 0 0-2.73-.73l-.15.08a2 2 0 0 1-2 0l-.43-.25a2 2 0 0 1-1-1.73V4a2 2 0 0 0-2-2z" />
      <circle cx="12" cy="12" r="3" />
    </svg>
  );
}

function ConsoleLayout() {
  const location = useLocation();
  const isFlushRoute = location.pathname.startsWith("/assistant");
  const [sidebarCollapsed, setSidebarCollapsed] = useState<boolean>(() => {
    try {
      return JSON.parse(window.localStorage.getItem(SIDEBAR_COLLAPSED_KEY) ?? "false") === true;
    } catch {
      return false;
    }
  });
  // Below this width the sidebar becomes a horizontal top bar (see index.css) where a
  // narrow icon-only rail doesn't apply -- ignore the stored preference there rather than
  // stripping nav labels out of a layout that still needs them.
  const [isNarrowViewport, setIsNarrowViewport] = useState(
    () => window.matchMedia("(max-width: 1080px)").matches,
  );

  useEffect(() => {
    window.localStorage.setItem(SIDEBAR_COLLAPSED_KEY, JSON.stringify(sidebarCollapsed));
  }, [sidebarCollapsed]);

  useEffect(() => {
    const mq = window.matchMedia("(max-width: 1080px)");
    const handler = (event: MediaQueryListEvent) => setIsNarrowViewport(event.matches);
    mq.addEventListener("change", handler);
    return () => mq.removeEventListener("change", handler);
  }, []);

  const collapsed = sidebarCollapsed && !isNarrowViewport;

  return (
    <div className={`console-shell${collapsed ? " sidebar-collapsed" : ""}`}>
      <aside className={`sidebar contour${collapsed ? " collapsed" : ""}`}>
        <Link to="/" className="brand-block" title="Aegis Crime Analytics Assistant">
          {collapsed ? (
            <img className="brand-mark" src={aegisLogo} alt="Aegis" />
          ) : (
            <img
              className="brand-lockup-image"
              src={aegisBrandImage}
              alt="Aegis Crime Analytics Assistant"
            />
          )}
        </Link>
        <nav className="sidebar-nav" aria-label="Main navigation">
          <NavLink
            to="/dashboard"
            className={({ isActive }) => `sidebar-link${isActive ? " active" : ""}`}
            title="Overview"
          >
            <NavIcon name="overview" />
            {!collapsed && <span>Overview</span>}
          </NavLink>
          <NavLink
            to="/ingest"
            className={({ isActive }) => `sidebar-link${isActive ? " active" : ""}`}
            title="Ingest"
          >
            <NavIcon name="ingest" />
            {!collapsed && <span>Ingest</span>}
          </NavLink>
          <NavLink
            to="/assistant"
            className={({ isActive }) => `sidebar-link${isActive ? " active" : ""}`}
            title="Assistant"
          >
            <NavIcon name="assistant" />
            {!collapsed && <span>Assistant</span>}
          </NavLink>
        </nav>
        <div className="sidebar-spacer" />
        <nav className="sidebar-nav sidebar-nav-bottom" aria-label="Settings navigation">
          <NavLink
            to="/admin"
            className={({ isActive }) => `sidebar-link${isActive ? " active" : ""}`}
            title="Admin"
          >
            <NavIcon name="admin" />
            {!collapsed && <span>Admin</span>}
          </NavLink>
        </nav>
        {!isNarrowViewport && (
          <button
            type="button"
            className="sidebar-collapse-toggle"
            onClick={() => setSidebarCollapsed((current) => !current)}
            title={collapsed ? "Expand sidebar" : "Collapse sidebar"}
          >
            <AssistantIcon name={collapsed ? "chevron-right" : "chevron-left"} />
          </button>
        )}
      </aside>
      <main className="main-panel">
        <div className={`main-content${isFlushRoute ? " flush" : ""}`}>
          <Outlet />
        </div>
      </main>
    </div>
  );
}

const WORKFLOW_STEPS: Array<{ step: string; title: string; body: string; to: string; cta: string }> = [
  {
    step: "01",
    title: "Ingest documents",
    body: "Pick a demo scenario or upload FIR/IR files. The pipeline extracts people, accounts, UPIs, phones and devices against a versioned schema.",
    to: "/ingest",
    cta: "Open ingest",
  },
  {
    step: "02",
    title: "Review and confirm",
    body: "Ambiguous entity matches are surfaced for the officer. Nothing is written to the graph until you approve — human stays in command.",
    to: "/ingest",
    cta: "See review",
  },
  {
    step: "03",
    title: "Investigate with the assistant",
    body: "Ask questions in plain language. The multi-agent engine queries SQL, the Neo4j graph and the vector store, and shows its reasoning with cited sources.",
    to: "/assistant",
    cta: "Open assistant",
  },
  {
    step: "04",
    title: "Configure the schema",
    body: "Admins control the entity-match threshold and the extraction schema mapping for each file type — FIR, IR and evidence.",
    to: "/admin",
    cta: "Open admin",
  },
];

const FEATURE_CARDS: Array<{ icon: string; title: string; body: string }> = [
  {
    icon: "graph",
    title: "Entity-network graph",
    body: "Every case becomes a graph of people, accounts and transfers — revealing hubs, mules and ring leaders across otherwise separate FIRs.",
  },
  {
    icon: "search",
    title: "Unified retrieval",
    body: "One question fans out to structured SQL, graph traversals and semantic vector search, then synthesises a single grounded answer.",
  },
  {
    icon: "shield",
    title: "Officer-in-command",
    body: "Confidence-scored matches are gated behind human review. The audit trail records who approved what, and when.",
  },
  {
    icon: "cite",
    title: "Cited by source",
    body: "Answers link back to the exact FIR, report or evidence file in the Stratus bucket, so findings are always defensible.",
  },
];

function FeatureIcon({ name }: { name: string }) {
  const common = {
    width: 22,
    height: 22,
    viewBox: "0 0 24 24",
    fill: "none",
    stroke: "currentColor",
    strokeWidth: 1.7,
    strokeLinecap: "round" as const,
    strokeLinejoin: "round" as const,
  };
  if (name === "graph") {
    return (
      <svg {...common}>
        <circle cx="6" cy="6" r="2.4" />
        <circle cx="18" cy="7" r="2.4" />
        <circle cx="12" cy="17" r="2.4" />
        <path d="M8 7l8 0.6M7.4 8.2 10.8 15M16.6 9 13.2 15" />
      </svg>
    );
  }
  if (name === "search") {
    return (
      <svg {...common}>
        <circle cx="10.5" cy="10.5" r="6.5" />
        <path d="M20 20l-4.5-4.5" />
      </svg>
    );
  }
  if (name === "shield") {
    return (
      <svg {...common}>
        <path d="M12 3l7 3v5c0 4.4-3 8-7 10-4-2-7-5.6-7-10V6z" />
        <path d="M9 12l2 2 4-4" />
      </svg>
    );
  }
  return (
    <svg {...common}>
      <path d="M7 4h7l4 4v12H7z" />
      <path d="M14 4v4h4M9.5 13h5M9.5 16h5" />
    </svg>
  );
}

function DashboardPage() {
  return (
    <div className="page-wrap">
      <header className="page-head">
        <div className="page-head-copy">
          <p className="kicker">Overview</p>
          <h2>Overview</h2>
          <p className="page-subtitle">
            Move from case documents to a connected intelligence picture. The workflow runs in four
            steps: ingest, review, investigate, and configure.
          </p>
          <p className="demo-officer-note">
            Demo officer identity:{" "}
            <strong>
              {FIXED_DEMO_USER.rank} {FIXED_DEMO_USER.name}
            </strong>{" "}
            · {FIXED_DEMO_USER.station} · {FIXED_DEMO_USER.kgid}. All uploads and assistant sessions
            are attributed to this sample officer.
          </p>
        </div>
        <UserProfileMenu />
      </header>

      <section className="guide-steps">
        {WORKFLOW_STEPS.map((item) => (
          <article key={item.step} className="card guide-step">
            <span className="guide-step-num">{item.step}</span>
            <h3>{item.title}</h3>
            <p>{item.body}</p>
            <Link to={item.to} className="guide-step-link">
              {item.cta} →
            </Link>
          </article>
        ))}
      </section>

      <section className="feature-grid">
        {FEATURE_CARDS.map((feature) => (
          <article key={feature.title} className="card feature-card">
            <span className="feature-icon">
              <FeatureIcon name={feature.icon} />
            </span>
            <div>
              <h3>{feature.title}</h3>
              <p>{feature.body}</p>
            </div>
          </article>
        ))}
      </section>

      <section className="card panel cta-banner">
        <div>
          <h3>Run a case</h3>
          <p className="muted">
            Load one of the four sample scenarios to run the ingestion pipeline.
          </p>
        </div>
        <div className="action-row">
          <Link to="/ingest" className="btn btn-primary">
            Start ingestion
          </Link>
          <Link to="/assistant" className="btn btn-ghost">
            Open assistant
          </Link>
        </div>
      </section>
    </div>
  );
}

function IngestPage() {
  const [caseMode, setCaseMode] = useState<"new" | "existing">("new");
  const [selectedCaseId, setSelectedCaseId] = useState<number | null>(null);
  const [caseOptions, setCaseOptions] = useState<CaseSummary[]>([]);
  const [draftFiles, setDraftFiles] = useState<DraftFile[]>([]);
  const [runId, setRunId] = useState<string | null>(null);
  const [run, setRun] = useState<PipelineRun | null>(null);
  const [findings, setFindings] = useState<FindingsResponse | null>(null);
  const [pendingReviewCount, setPendingReviewCount] = useState<number | null>(null);
  const [reviewItems, setReviewItems] = useState<ReviewQueueItem[]>([]);
  const [busy, setBusy] = useState<boolean>(false);
  const [busyLabel, setBusyLabel] = useState<string>("");
  const [notice, setNotice] = useState<string | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [activeScenarioId, setActiveScenarioId] = useState<string | null>(null);
  const [scenarioGeneration, setScenarioGeneration] = useState<number | null>(null);
  const [scenarioResetToken, setScenarioResetToken] = useState<string | null>(null);

  const totalUploadBytes = useMemo(
    () => draftFiles.reduce((sum, entry) => sum + entry.file.size, 0),
    [draftFiles],
  );

  const activeScenario = useMemo(
    () => DEMO_SCENARIOS.find((s) => s.id === activeScenarioId) ?? null,
    [activeScenarioId],
  );

  const scenarioLocked = activeScenarioId !== null;

  // Restore run from localStorage on mount
  useEffect(() => {
    const savedRunId = window.localStorage.getItem(CURRENT_RUN_STORAGE_KEY);
    if (savedRunId && !runId) {
      setRunId(savedRunId);
    }
  }, []); // eslint-disable-line react-hooks/exhaustive-deps

  async function loadScenario(scenario: DemoScenario): Promise<void> {
    setBusy(true);
    setBusyLabel("Loading scenario files...");
    setError(null);
    setNotice(null);
    try {
      const loaded: DraftFile[] = [];
      for (const doc of scenario.documents) {
        const resp = await fetch(doc.path);
        if (!resp.ok) {
          throw new Error(`Could not load ${doc.name} for ${scenario.shortTitle}.`);
        }
        const blob = await resp.blob();
        const file = new File([blob], doc.name, { type: blob.type || "text/plain" });
        loaded.push({ id: makeId("file"), file, fileType: doc.fileType });
      }
      setCaseMode("new");
      setSelectedCaseId(null);
      setDraftFiles(loaded);
      setActiveScenarioId(scenario.id);
      setNotice(
        `${scenario.shortTitle}: ${loaded.length} document(s) staged (CrimeNo: ${scenario.crimeNo}). Review below, then run the pipeline.`,
      );
    } catch (loadErr) {
      setError(loadErr instanceof Error ? loadErr.message : "Failed to load scenario documents.");
    } finally {
      setBusy(false);
      setBusyLabel("");
    }
  }

  function clearScenario(): void {
    setActiveScenarioId(null);
    setScenarioGeneration(null);
    setScenarioResetToken(null);
    setDraftFiles([]);
    setNotice(null);
  }

  useEffect(() => {
    let cancelled = false;
    void listCases(200)
      .then((items) => {
        if (!cancelled) {
          setCaseOptions(items);
          if (items.length > 0) {
            setSelectedCaseId((current) => current ?? items[0].case_master_id);
          }
        }
      })
      .catch(() => {
        if (!cancelled) {
          setCaseOptions([]);
        }
      });
    return () => {
      cancelled = true;
    };
  }, []);

  useEffect(() => {
    if (!runId) {
      setRun(null);
      return;
    }
    let cancelled = false;
    void getPipelineStatus(runId)
      .then((status) => {
        if (!cancelled) {
          setRun(status);
        }
      })
      .catch(() => {
        if (!cancelled) {
          setRun(null);
          window.localStorage.removeItem(CURRENT_RUN_STORAGE_KEY);
          setRunId(null);
        }
      });
    return () => {
      cancelled = true;
    };
  }, [runId]);

  // Both effects below depend on [runId] only, not on `run`. Including `run` caused
  // a reconnect/reset storm: every incoming message called setRun(), which re-ran
  // the effects, which tore down and reopened the socket / interval, which
  // immediately fetched again and called setRun() again -- observed as a new WS
  // connection roughly every 200-300ms instead of the intended handful-of-seconds
  // cadence. Terminal status is instead handled by each effect closing/clearing
  // itself once a terminal payload arrives (not by gating on mount), since gating
  // on a stale `run` left over from a *previous* run_id would otherwise skip
  // attaching updates entirely for the next run in the same page session.
  useEffect(() => {
    if (!runId) {
      return;
    }

    let closedByTerminalStatus = false;
    const ws = new WebSocket(buildPipelineWebSocketUrl(runId));
    ws.onmessage = (event) => {
      try {
        const payload = JSON.parse(event.data) as PipelineRun & { status?: string };
        if (payload.status === "NOT_FOUND") {
          return;
        }
        setRun(payload);
        if (payload.status && TERMINAL_PIPELINE_STATUSES.has(payload.status)) {
          closedByTerminalStatus = true;
          ws.close();
        }
      } catch {
        setError("Failed to parse live pipeline update.");
      }
    };
    ws.onerror = () => {
      if (!closedByTerminalStatus) {
        setError("Live pipeline socket disconnected. Using status polling fallback.");
      }
    };

    return () => {
      ws.close();
    };
  }, [runId]);

  useEffect(() => {
    if (!runId) {
      return;
    }
    // Backstop only -- the WebSocket above is push-driven and carries most updates,
    // so this can run infrequently without hurting perceived responsiveness.
    const timer = window.setInterval(() => {
      void getPipelineStatus(runId)
        .then((status) => {
          setRun(status);
          if (status.status && TERMINAL_PIPELINE_STATUSES.has(status.status)) {
            window.clearInterval(timer);
          }
        })
        .catch(() => {
          setError("Polling pipeline status failed.");
        });
    }, STATUS_POLL_INTERVAL_MS);
    return () => {
      window.clearInterval(timer);
    };
  }, [runId]);

  useEffect(() => {
    if (!runId || !run || run.status !== "REVIEW_PENDING") {
      setFindings(null);
      setPendingReviewCount(null);
      setReviewItems([]);
      return;
    }
    const activeRunId = runId;

    let cancelled = false;
    async function loadReviewData() {
      try {
        const [findingsResp, queueResp] = await Promise.all([
          getFindings(activeRunId),
          getReviewQueue(activeRunId),
        ]);
        if (cancelled) {
          return;
        }
        setFindings(findingsResp);
        setPendingReviewCount(queueResp.count);
        setReviewItems(queueResp.items || []);
      } catch (reviewErr) {
        if (!cancelled) {
          setError(reviewErr instanceof Error ? reviewErr.message : "Failed to load review summary.");
        }
      }
    }
    void loadReviewData();
    return () => {
      cancelled = true;
    };
  }, [run, runId]);

  const canStart = draftFiles.length > 0 && (caseMode === "new" || selectedCaseId !== null) && !busy;

  function handleCaseMode(nextMode: "new" | "existing"): void {
    if (scenarioLocked) return;
    setCaseMode(nextMode);
  }

  async function handleResolveReview(reviewId: number, decision: "merge" | "keep_separate"): Promise<void> {
    setBusy(true);
    setError(null);
    try {
      await resolveReviewItem(
        reviewId,
        decision,
        `${FIXED_DEMO_USER.rank} ${FIXED_DEMO_USER.name}`,
      );
      // Refresh review queue
      if (runId) {
        const queueResp = await getReviewQueue(runId);
        setReviewItems(queueResp.items || []);
        setPendingReviewCount(queueResp.count);
      }
    } catch (err) {
      setError(err instanceof Error ? err.message : "Failed to resolve review item.");
    } finally {
      setBusy(false);
    }
  }

  function handleFileSelection(fileList: FileList | null): void {
    if (!fileList || scenarioLocked) {
      return;
    }
    const newEntries: DraftFile[] = Array.from(fileList).map((file) => ({
      id: makeId("file"),
      file,
      fileType: caseMode === "new" ? "fir" : "evidence",
    }));
    setDraftFiles((existingDrafts) => [...existingDrafts, ...newEntries].slice(0, 15));
    setNotice(null);
    setError(null);
  }

  function removeDraftFile(id: string): void {
    setDraftFiles((existingDrafts) => existingDrafts.filter((entry) => entry.id !== id));
  }

  function updateDraftType(id: string, fileType: UploadFileType): void {
    setDraftFiles((existingDrafts) =>
      existingDrafts.map((entry) => (entry.id === id ? { ...entry, fileType } : entry)),
    );
  }

  async function handleStartRun(): Promise<void> {
    if (!canStart) {
      return;
    }
    setBusy(true);
    setError(null);
    setNotice(null);
    try {
      let currentGeneration = scenarioGeneration;
      let currentToken = scenarioResetToken;

      // If this is a scenario run, prepare/reset first
      if (activeScenarioId) {
        setBusyLabel("Resetting previous data...");
        const idempotencyKey = `${activeScenarioId}-${Date.now()}`;
        const prepareResult = await prepareScenario(activeScenarioId, idempotencyKey);
        currentGeneration = prepareResult.generation;
        currentToken = prepareResult.reset_token;
        setScenarioGeneration(currentGeneration);
        setScenarioResetToken(currentToken);
      }

      setBusyLabel("Uploading files...");
      const payloadFiles: UploadFileEntry[] = draftFiles.map((entry) => ({
        file: entry.file,
        fileType: entry.fileType,
      }));
      const uploadResponse = await uploadDocuments({
        files: payloadFiles,
        caseId: caseMode === "existing" ? selectedCaseId : null,
        uploadedBy: `${FIXED_DEMO_USER.rank} ${FIXED_DEMO_USER.name} - ${FIXED_DEMO_USER.kgid}`,
        scenarioKey: activeScenarioId ?? undefined,
        scenarioGeneration: currentGeneration ?? undefined,
        resetToken: currentToken ?? undefined,
      });
      const storedCount = uploadResponse.files.filter((item) => item.status === "STORED").length;
      if (storedCount === 0) {
        const failedMsgs = uploadResponse.files
          .filter((item) => item.status === "FAILED")
          .map((item) => `${item.filename}: ${item.message}`)
          .join("; ");
        throw new Error(`Upload finished but no files were accepted. ${failedMsgs}`);
      }

      setBusyLabel("Starting pipeline...");
      const processResponse = await startProcess(uploadResponse.batch_id);
      setRunId(processResponse.run_id);
      window.localStorage.setItem(CURRENT_RUN_STORAGE_KEY, processResponse.run_id);

      try {
        const status = await getPipelineStatus(processResponse.run_id);
        setRun(status);
      } catch {
        setRun({
          run_id: processResponse.run_id,
          batch_id: processResponse.batch_id || uploadResponse.batch_id,
          case_id: processResponse.case_id || uploadResponse.case_id || 0,
          phase: processResponse.phase,
          status: processResponse.status,
          current_stage: "QUEUED",
        });
      }

      setNotice(`Run ${processResponse.run_id} started. Monitoring current run only.`);
    } catch (startErr) {
      setError(startErr instanceof Error ? startErr.message : "Failed to start ingestion.");
    } finally {
      setBusy(false);
      setBusyLabel("");
    }
  }

  async function handleProceed(): Promise<void> {
    if (!runId) {
      return;
    }
    setBusy(true);
    setError(null);
    try {
      await proceedRun(runId);
      const next = await getPipelineStatus(runId);
      setRun(next);
      setNotice(`Run ${runId} moved to load phase.`);
    } catch (proceedErr) {
      setError(proceedErr instanceof Error ? proceedErr.message : "Failed to proceed run.");
    } finally {
      setBusy(false);
    }
  }

  async function handleRetry(): Promise<void> {
    if (!runId) {
      return;
    }
    setBusy(true);
    setError(null);
    try {
      await retryRun(runId);
      const next = await getPipelineStatus(runId);
      setRun(next);
      setNotice(`Retry submitted for run ${runId}.`);
    } catch (retryErr) {
      setError(retryErr instanceof Error ? retryErr.message : "Failed to retry run.");
    } finally {
      setBusy(false);
    }
  }

  function clearCurrentRun(): void {
    setRunId(null);
    setRun(null);
    setFindings(null);
    setPendingReviewCount(null);
    window.localStorage.removeItem(CURRENT_RUN_STORAGE_KEY);
  }

  return (
    <div className="page-wrap">
      <header className="page-head">
        <div className="page-head-copy">
          <p className="kicker">Ingestion</p>
          <h2>Data ingestion</h2>
          <p className="page-subtitle">
            Select a prepared scenario to stage its FIR, then run the ingestion pipeline and monitor
            the current run.
          </p>
        </div>
        <UserProfileMenu />
      </header>

      {notice && <p className="alert alert-ok">{notice}</p>}
      {error && <p className="alert alert-danger">{error}</p>}

      <section className="card panel scenario-picker">
        <div className="section-headline">
          <h3>Demo scenario</h3>
        </div>
        <div className="scenario-picker-row">
          <select
            className="scenario-dropdown"
            value={activeScenarioId ?? ""}
            onChange={(e) => {
              const scenario = DEMO_SCENARIOS.find((s) => s.id === e.target.value);
              if (scenario) void loadScenario(scenario);
            }}
            disabled={busy}
          >
            <option value="">Select a scenario...</option>
            {DEMO_SCENARIOS.map((scenario) => (
              <option key={scenario.id} value={scenario.id}>
                {scenario.shortTitle} — {scenario.ingestHook}
              </option>
            ))}
          </select>
          {scenarioLocked && (
            <button className="btn btn-ghost btn-sm" type="button" onClick={clearScenario} disabled={busy}>
              Remove scenario
            </button>
          )}
        </div>
        {activeScenario && (
          <div className="scenario-detail-compact">
            <p><strong>{activeScenario.title}</strong> — {activeScenario.description}</p>
            <p className="mono muted">CrimeNo: {activeScenario.crimeNo} · {activeScenario.documents.length} files</p>
          </div>
        )}
      </section>

      <div className="ingest-grid">
        <section className="card panel">
          <div className="section-headline">
            <h3>1. Staged files</h3>
          </div>
          <div className="toggle-row">
            <button
              className={`chip-button${caseMode === "new" ? " active" : ""}`}
              type="button"
              onClick={() => handleCaseMode("new")}
              disabled={scenarioLocked}
            >
              Start new case
            </button>
            <button
              className={`chip-button${caseMode === "existing" ? " active" : ""}`}
              type="button"
              onClick={() => handleCaseMode("existing")}
              disabled={scenarioLocked}
            >
              Add to existing case
            </button>
          </div>

          {caseMode === "existing" && !scenarioLocked && (
            <label className="stack-label">
              Select case
              <select
                value={selectedCaseId ?? ""}
                onChange={(event) =>
                  setSelectedCaseId(event.target.value ? Number(event.target.value) : null)
                }
              >
                {caseOptions.map((option) => (
                  <option key={option.case_master_id} value={option.case_master_id}>
                    Case {option.case_master_id} - {option.crime_no || option.case_no || "Unknown"}
                  </option>
                ))}
              </select>
            </label>
          )}

          {!scenarioLocked && (
            <label className="drop-zone-label">
              <span className="drop-zone-content">
                <svg width="28" height="28" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.5" strokeLinecap="round" strokeLinejoin="round">
                  <path d="M21 15v4a2 2 0 0 1-2 2H5a2 2 0 0 1-2-2v-4" />
                  <polyline points="17 8 12 3 7 8" />
                  <line x1="12" y1="3" x2="12" y2="15" />
                </svg>
                <span>Drop files here or click to choose</span>
                <span className="muted">Accepted: txt, html, pdf, csv, docx, images</span>
              </span>
              <input
                type="file"
                multiple
                className="drop-zone-input"
                onChange={(event) => {
                  handleFileSelection(event.target.files);
                  event.currentTarget.value = "";
                }}
              />
            </label>
          )}

          <p className="muted">
            {draftFiles.length} files staged | {formatFileSize(totalUploadBytes)} total
          </p>

          <ul className="file-list">
            {draftFiles.map((entry) => (
              <li key={entry.id} className="file-row">
                <div className="file-meta">
                  <strong>{entry.file.name}</strong>
                  <span>{formatFileSize(entry.file.size)}</span>
                </div>
                <select
                  value={entry.fileType}
                  onChange={(event) => updateDraftType(entry.id, event.target.value as UploadFileType)}
                  disabled={scenarioLocked}
                >
                  <option value="fir">FIR</option>
                  <option value="ir">Investigation Report</option>
                  <option value="evidence">Evidence</option>
                </select>
                {!scenarioLocked && (
                  <button className="btn btn-ghost btn-sm" type="button" onClick={() => removeDraftFile(entry.id)}>
                    Remove
                  </button>
                )}
              </li>
            ))}
          </ul>

          <div className="action-row">
            <button className="btn btn-primary" type="button" disabled={!canStart} onClick={() => void handleStartRun()}>
              {busy ? (busyLabel || "Working...") : "Run ingestion pipeline"}
            </button>
            {!scenarioLocked && (
              <button
                className="btn btn-ghost"
                type="button"
                onClick={() => {
                  setDraftFiles([]);
                  setActiveScenarioId(null);
                }}
              >
                Clear files
              </button>
            )}
          </div>
        </section>

        <section className="card panel">
          <div className="section-headline">
            <h3>2. Current run status</h3>
          </div>
          {!run ? (
            <p className="muted">No active run. Start ingestion to begin monitoring.</p>
          ) : (
            <div className="status-block">
              <div className={`status-pill ${statusTone(run.status)}`}>{run.status_label || run.status}</div>
              <p className="mono">Run ID: {run.run_id}</p>
              <p>Case ID: {run.case_id}</p>
              <p>Stage: {run.stage_label || run.current_stage}</p>
              {run.error_message && <p className="text-danger">{run.error_message}</p>}
              <p>Updated: {formatDate(run.updated_at)}</p>

              {run.files_progress && Object.keys(run.files_progress).filter((k) => k !== "_meta").length > 0 && (
                <ul className="simple-list compact">
                  {Object.entries(run.files_progress)
                    .filter(([fileName]) => fileName !== "_meta")
                    .map(([fileName, progress]) => (
                    <li key={fileName}>
                      <strong>{fileName}</strong>
                      <span>{progress.stage_label || progress.stage || progress.status_label || "Pending"}</span>
                    </li>
                  ))}
                </ul>
              )}

              <div className="action-row">
                {run.status === "FAILED" && (
                  <button className="btn btn-danger btn-sm" type="button" onClick={() => void handleRetry()}>
                    Retry current phase
                  </button>
                )}
                <button className="btn btn-ghost btn-sm" type="button" onClick={clearCurrentRun}>
                  Clear run context
                </button>
              </div>
            </div>
          )}
        </section>
      </div>

      {run && run.status === "REVIEW_PENDING" && (
        <section className="card panel review-inline">
          <div className="section-headline">
            <h3>3. Human review</h3>
            <div className="status-pill warn">Officer action required</div>
          </div>
          {findings ? (
            <div className="stats-row">
              <div>
                <span className="stat-label">People</span>
                <strong>{findings.counts.people}</strong>
              </div>
              <div>
                <span className="stat-label">Bank accounts</span>
                <strong>{findings.counts.bank_accounts}</strong>
              </div>
              <div>
                <span className="stat-label">Transactions</span>
                <strong>{findings.counts.transactions}</strong>
              </div>
              <div>
                <span className="stat-label">Pending reviews</span>
                <strong>{pendingReviewCount ?? 0}</strong>
              </div>
            </div>
          ) : (
            <p className="muted">Loading findings summary...</p>
          )}

          {findings && (
            <div className="findings-detail">
              {findings.files.length > 0 && (
                <div className="findings-section">
                  <h4>Documents processed</h4>
                  <ul className="simple-list compact">
                    {findings.files.map((f) => (
                      <li key={f.filename}>
                        <strong>{f.filename}</strong>
                        <span>{f.doc_type_label}: {f.summary}</span>
                      </li>
                    ))}
                  </ul>
                </div>
              )}

              {findings.entities.people.length > 0 && (
                <div className="findings-section">
                  <h4>People ({findings.entities.people.length})</h4>
                  <div className="table-wrap">
                    <table>
                      <thead>
                        <tr>
                          <th>Name</th>
                          <th>Role</th>
                          <th>Source file</th>
                        </tr>
                      </thead>
                      <tbody>
                        {findings.entities.people.map((p, i) => (
                          <tr key={i}>
                            <td>{p.name}</td>
                            <td>{p.role}</td>
                            <td className="mono">{p.file}</td>
                          </tr>
                        ))}
                      </tbody>
                    </table>
                  </div>
                </div>
              )}

              {(findings.entities.bank_accounts.length > 0 ||
                findings.entities.upi_handles.length > 0 ||
                findings.entities.phone_numbers.length > 0 ||
                findings.entities.devices.length > 0) && (
                <div className="findings-section">
                  <h4>Financial &amp; device identifiers</h4>
                  <div className="table-wrap">
                    <table>
                      <thead>
                        <tr>
                          <th>Type</th>
                          <th>Identifier</th>
                          <th>Detail</th>
                          <th>Source file</th>
                        </tr>
                      </thead>
                      <tbody>
                        {findings.entities.bank_accounts.map((a, i) => (
                          <tr key={`acc-${i}`}>
                            <td>Bank account</td>
                            <td className="mono">{a.account_number}</td>
                            <td>{[a.holder_name, a.bank_name].filter(Boolean).join(" · ") || "—"}</td>
                            <td className="mono">{a.file}</td>
                          </tr>
                        ))}
                        {findings.entities.upi_handles.map((u, i) => (
                          <tr key={`upi-${i}`}>
                            <td>UPI</td>
                            <td className="mono">{u.vpa}</td>
                            <td>{u.holder_name || "—"}</td>
                            <td className="mono">{u.file}</td>
                          </tr>
                        ))}
                        {findings.entities.phone_numbers.map((p, i) => (
                          <tr key={`ph-${i}`}>
                            <td>Phone</td>
                            <td className="mono">{p.number}</td>
                            <td>{p.holder_name || "—"}</td>
                            <td className="mono">{p.file}</td>
                          </tr>
                        ))}
                        {findings.entities.devices.map((d, i) => (
                          <tr key={`dev-${i}`}>
                            <td>Device (IMEI)</td>
                            <td className="mono">{d.imei}</td>
                            <td>—</td>
                            <td className="mono">{d.file}</td>
                          </tr>
                        ))}
                      </tbody>
                    </table>
                  </div>
                </div>
              )}

              {findings.transactions.length > 0 && (
                <div className="findings-section">
                  <h4>Transactions ({findings.transactions.length})</h4>
                  <div className="table-wrap">
                    <table>
                      <thead>
                        <tr>
                          <th>From</th>
                          <th>To</th>
                          <th>Amount</th>
                          <th>Date</th>
                          <th>Mode</th>
                          <th>Source file</th>
                        </tr>
                      </thead>
                      <tbody>
                        {findings.transactions.map((t, i) => (
                          <tr key={i}>
                            <td className="mono">{t.from}</td>
                            <td className="mono">{t.to}</td>
                            <td>₹{Number(t.amount).toLocaleString("en-IN")}</td>
                            <td>{formatDate(t.date ?? undefined)}</td>
                            <td>{t.mode || "—"}</td>
                            <td className="mono">{t.file}</td>
                          </tr>
                        ))}
                      </tbody>
                    </table>
                  </div>
                </div>
              )}
            </div>
          )}

          {reviewItems.length > 0 && (
            <div className="review-items-list">
              {reviewItems.map((item) => {
                const confidence = Math.round((item.match_score ?? 0) * 100);
                const level = confidence >= 80 ? "high" : confidence >= 50 ? "medium" : "low";
                return (
                  <article key={item.review_id} className={`review-item-card confidence-${level}`}>
                    <div className="review-item-header">
                      <span className={`confidence-badge ${level}`}>
                        {confidence}% · {level === "high" ? "High" : level === "medium" ? "Medium" : "Low"} confidence
                      </span>
                      <span className="review-entity-type">{item.entity_type}</span>
                    </div>
                    <div className="review-item-body">
                      <div className="review-candidate">
                        <span className="review-label">Candidate</span>
                        <strong>{item.candidate_name || "Unknown"}</strong>
                      </div>
                      <span className="review-vs">↔</span>
                      <div className="review-matched">
                        <span className="review-label">Existing record</span>
                        <strong>{(item.matched_record as Record<string, string>)?.name || item.matched_against_entity_uid?.slice(0, 8)}</strong>
                      </div>
                    </div>
                    {item.match_reasons && item.match_reasons.length > 0 && (
                      <p className="review-reasons muted">{item.match_reasons.join(" · ")}</p>
                    )}
                    <div className="action-row">
                      <button
                        className="btn btn-primary btn-sm"
                        type="button"
                        onClick={() => void handleResolveReview(item.review_id, "merge")}
                        disabled={busy}
                      >
                        Merge
                      </button>
                      <button
                        className="btn btn-ghost btn-sm"
                        type="button"
                        onClick={() => void handleResolveReview(item.review_id, "keep_separate")}
                        disabled={busy}
                      >
                        Keep separate
                      </button>
                    </div>
                  </article>
                );
              })}
            </div>
          )}

          <button
            className="btn btn-primary"
            type="button"
            onClick={() => void handleProceed()}
            disabled={busy || (pendingReviewCount != null && pendingReviewCount > 0)}
          >
            {pendingReviewCount && pendingReviewCount > 0
              ? `Resolve ${pendingReviewCount} item(s) to proceed`
              : "Proceed to load phase"}
          </button>
        </section>
      )}
    </div>
  );
}

function AdminPage() {
  const [threshold, setThreshold] = useState<number>(0.8);
  const [savedThreshold, setSavedThreshold] = useState<number>(0.8);
  const [schemas, setSchemas] = useState<ActiveSchemaSummary[]>([]);
  const [selectedDocType, setSelectedDocType] = useState<string>("");
  const [schemaDetail, setSchemaDetail] = useState<SchemaDetailResponse | null>(null);
  const [schemaVersions, setSchemaVersions] = useState<SchemaVersionSummary[]>([]);
  const [activeTab, setActiveTab] = useState<"versions" | "fields" | "relationships">("fields");
  const [busy, setBusy] = useState<boolean>(false);
  const [error, setError] = useState<string | null>(null);
  const [notice, setNotice] = useState<string | null>(null);

  useEffect(() => {
    let cancelled = false;
    async function loadAdminData() {
      try {
        setError(null);
        const [thresholdResp, schemaList] = await Promise.all([getThreshold(), listActiveSchemas()]);
        if (cancelled) {
          return;
        }
        setThreshold(thresholdResp.value);
        setSavedThreshold(thresholdResp.value);
        setSchemas(schemaList);
        if (schemaList.length > 0) {
          setSelectedDocType((current) => current || schemaList[0].doc_type);
        }
      } catch (loadErr) {
        if (!cancelled) {
          setError(loadErr instanceof Error ? loadErr.message : "Failed to load admin data.");
        }
      }
    }
    void loadAdminData();
    return () => {
      cancelled = true;
    };
  }, []);

  useEffect(() => {
    if (!selectedDocType) {
      return;
    }
    let cancelled = false;
    async function loadSchemaDetail() {
      try {
        const [detail, versions] = await Promise.all([
          getSchemaDetail(selectedDocType),
          getSchemaVersions(selectedDocType),
        ]);
        if (cancelled) {
          return;
        }
        setSchemaDetail(detail);
        setSchemaVersions(versions);
      } catch (loadErr) {
        if (!cancelled) {
          setError(loadErr instanceof Error ? loadErr.message : "Failed to load schema detail.");
        }
      }
    }
    void loadSchemaDetail();
    return () => {
      cancelled = true;
    };
  }, [selectedDocType]);

  async function handleSaveThreshold(): Promise<void> {
    setBusy(true);
    setError(null);
    setNotice(null);
    try {
      const response = await updateThreshold(
        threshold,
        `${FIXED_DEMO_USER.rank} ${FIXED_DEMO_USER.name}`,
      );
      setSavedThreshold(response.value);
      setNotice(`Threshold saved at ${response.value.toFixed(2)}.`);
    } catch (saveErr) {
      setError(saveErr instanceof Error ? saveErr.message : "Failed to save threshold.");
    } finally {
      setBusy(false);
    }
  }

  async function handleActivateVersion(version: number): Promise<void> {
    if (!selectedDocType) {
      return;
    }
    setBusy(true);
    setError(null);
    setNotice(null);
    try {
      await activateSchemaVersion(selectedDocType, version);
      const [schemaList, detail, versions] = await Promise.all([
        listActiveSchemas(),
        getSchemaDetail(selectedDocType),
        getSchemaVersions(selectedDocType),
      ]);
      setSchemas(schemaList);
      setSchemaDetail(detail);
      setSchemaVersions(versions);
      setNotice(`${selectedDocType} is now active on version ${version}.`);
    } catch (activateErr) {
      setError(activateErr instanceof Error ? activateErr.message : "Failed to activate schema version.");
    } finally {
      setBusy(false);
    }
  }

  return (
    <div className="page-wrap">
      <header className="page-head">
        <div className="page-head-copy">
          <p className="kicker">Configuration</p>
          <h2>Admin</h2>
          <p className="page-subtitle">
            Set the entity review threshold and inspect how each FIR, IR and evidence schema maps
            extracted entities into SQL tables and graph objects.
          </p>
        </div>
        <UserProfileMenu />
      </header>
      {notice && <p className="alert alert-ok">{notice}</p>}
      {error && <p className="alert alert-danger">{error}</p>}

      <section className="card panel">
        <div className="section-headline">
          <h3>Entity match threshold</h3>
        </div>
        <div className="threshold-compact">
          <div>
            <p className="muted">
              Higher threshold means fewer auto-merge suggestions. Officer decision remains mandatory.
            </p>
            <p className="muted">Current saved value: {savedThreshold.toFixed(2)}</p>
          </div>
          <strong className="threshold-value">{threshold.toFixed(2)}</strong>
          <input
            type="range"
            min={0.5}
            max={0.99}
            step={0.01}
            value={threshold}
            onChange={(event) => setThreshold(Number(event.target.value))}
          />
          <div className="action-row">
            <button className="btn btn-primary btn-sm" type="button" onClick={() => void handleSaveThreshold()} disabled={busy}>
              Save
            </button>
            <button className="btn btn-ghost btn-sm" type="button" onClick={() => setThreshold(savedThreshold)}>
              Reset
            </button>
          </div>
        </div>
      </section>

      <section className="card panel">
        <div className="section-headline">
          <h3>Extraction schemas</h3>
        </div>
        {schemas.length === 0 ? (
          <p className="muted">No active schema rows found.</p>
        ) : (
          <div className="admin-grid">
            <aside className="schema-nav">
              {schemas.map((schema) => (
                <button
                  key={schema.doc_type}
                  className={`schema-nav-item${schema.doc_type === selectedDocType ? " active" : ""}`}
                  type="button"
                  onClick={() => setSelectedDocType(schema.doc_type)}
                >
                  {schema.doc_type} <span className="mono">v{schema.version}</span>
                </button>
              ))}
            </aside>
            <div className="schema-main">
              {!schemaDetail ? (
                <p className="muted">Loading schema detail...</p>
              ) : (
                <>
                  <div className="schema-head">
                    <h4>
                      {schemaDetail.schema.doc_type} schema (v{schemaDetail.schema.version})
                    </h4>
                    <p className="muted">{schemaDetail.schema.description || "No description provided."}</p>
                  </div>
                  <div className="tab-row">
                    <button
                      className={`chip-button${activeTab === "versions" ? " active" : ""}`}
                      type="button"
                      onClick={() => setActiveTab("versions")}
                    >
                      Versions
                    </button>
                    <button
                      className={`chip-button${activeTab === "fields" ? " active" : ""}`}
                      type="button"
                      onClick={() => setActiveTab("fields")}
                    >
                      Field mapping
                    </button>
                    <button
                      className={`chip-button${activeTab === "relationships" ? " active" : ""}`}
                      type="button"
                      onClick={() => setActiveTab("relationships")}
                    >
                      Relationships
                    </button>
                  </div>

                  {activeTab === "versions" && (
                    <ul className="simple-list">
                      {schemaVersions.map((version) => (
                        <li key={version.schema_id}>
                          <div>
                            <strong>Version {version.version}</strong>
                            <span>{version.description || "No description"}</span>
                          </div>
                          {version.is_active ? (
                            <span className="status-pill ok">Active</span>
                          ) : (
                            <button
                              className="btn btn-ghost btn-sm"
                              type="button"
                              onClick={() => void handleActivateVersion(version.version)}
                              disabled={busy}
                            >
                              Activate
                            </button>
                          )}
                        </li>
                      ))}
                    </ul>
                  )}

                  {activeTab === "fields" && (
                    <div className="table-wrap">
                      <table>
                        <thead>
                          <tr>
                            <th>File Type</th>
                            <th>Entity</th>
                            <th>Group</th>
                            <th>Field</th>
                            <th>Type</th>
                            <th>Target Table</th>
                            <th>Target Field</th>
                            <th>Required</th>
                            <th>Identifier</th>
                            <th>Action</th>
                          </tr>
                        </thead>
                        <tbody>
                          {schemaDetail.fields.map((field) => (
                            <tr key={field.field_id}>
                              <td>{schemaDetail.schema.doc_type}</td>
                              <td>{field.pole_entity_type || "Structured row"}</td>
                              <td>{field.group_name}</td>
                              <td>{field.field_name}</td>
                              <td>{field.data_type}</td>
                              <td className="mono">{field.target_table}</td>
                              <td className="mono">{field.target_column}</td>
                              <td>{field.is_required ? "Yes" : "No"}</td>
                              <td>{field.is_identifier ? field.identifier_type || "Yes" : "-"}</td>
                              <td>
                                <button className="btn btn-ghost btn-sm" type="button" disabled>
                                  Edit
                                </button>
                              </td>
                            </tr>
                          ))}
                        </tbody>
                      </table>
                    </div>
                  )}

                  {activeTab === "relationships" && (
                    <ul className="simple-list">
                      {schemaDetail.relationships.map((relationship) => (
                        <li key={relationship.relationship_id}>
                          <strong>
                            {relationship.from_group} - {relationship.relationship_type} - {relationship.to_group}
                          </strong>
                          <span>Direction: {relationship.direction}</span>
                        </li>
                      ))}
                    </ul>
                  )}
                </>
              )}
            </div>
          </div>
        )}
      </section>
    </div>
  );
}

export default App;
