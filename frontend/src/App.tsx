import { useEffect, useMemo, useRef, useState } from "react";
import type { FormEvent } from "react";
import {
  Link,
  Navigate,
  NavLink,
  Outlet,
  Route,
  Routes,
  useNavigate,
  useSearchParams,
} from "react-router-dom";
import { FIXED_DEMO_USER } from "./config/demoUser";
import { DEMO_SCENARIOS, type DemoScenario, type ScenarioPrompt } from "./data/scenarios";
import aegisBrandImage from "./assets/aegis-brand.png";
import {
  assistantClient,
  getScenarioResponse,
  type AssistantGraph,
  type AssistantResponse,
  type ToolKind,
} from "./lib/assistantClient";
import {
  activateSchemaVersion,
  buildPipelineWebSocketUrl,
  getCase,
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
  type CaseDetail,
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
const CURRENT_RUN_STORAGE_KEY = "crime-analytics-assistant.current-run-id";

type DraftFile = {
  id: string;
  file: File;
  fileType: UploadFileType;
};

type ChatMessage = {
  id: string;
  role: "user" | "assistant";
  content: string;
  response?: AssistantResponse;
  at?: string;
};

function nowLabel(): string {
  return new Date().toLocaleTimeString([], { hour: "2-digit", minute: "2-digit" });
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
            <button className="btn btn-primary btn-lg" type="button" onClick={() => navigate("/dashboard")}>
              Start analysis
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

        <div className="hero-visual">
          <svg
            viewBox="0 0 480 380"
            role="img"
            aria-label="Network insight: three district FIRs from Mysuru, Mangaluru and Hubballi funnel 54 lakh rupees into one HDFC hub account operated by accused Victor Hale, who uses three aliases."
          >
            {/* money-flow edges: victim FIRs -> hub */}
            <line className="edge money" x1="66" y1="64" x2="196" y2="190" />
            <line className="edge money" x1="50" y1="190" x2="196" y2="190" />
            <line className="edge money" x1="66" y1="316" x2="196" y2="190" />
            {/* control edge: hub -> ring leader */}
            <line className="edge control" x1="196" y1="190" x2="352" y2="190" />
            {/* alias edges: aliases -> ring leader */}
            <line className="edge alias" x1="430" y1="92" x2="352" y2="190" />
            <line className="edge alias" x1="430" y1="288" x2="352" y2="190" />

            {/* pulsing halo on the ring leader */}
            <circle className="leader-halo" cx="352" cy="190" r="30" />

            {/* nodes */}
            <circle className="dot" cx="66" cy="64" r="15" fill="#0b1020" stroke="#35e0ff" strokeWidth="2" />
            <circle className="dot n2" cx="50" cy="190" r="15" fill="#0b1020" stroke="#35e0ff" strokeWidth="2" />
            <circle className="dot n3" cx="66" cy="316" r="15" fill="#0b1020" stroke="#35e0ff" strokeWidth="2" />
            <circle className="dot n4" cx="196" cy="190" r="22" fill="#0b1020" stroke="#f7c948" strokeWidth="2.4" />
            <circle className="dot n5" cx="430" cy="92" r="14" fill="#0b1020" stroke="#8b7cff" strokeWidth="2" />
            <circle className="dot n6" cx="430" cy="288" r="14" fill="#0b1020" stroke="#8b7cff" strokeWidth="2" />
            <circle className="dot" cx="352" cy="190" r="30" fill="#141003" stroke="#f7c948" strokeWidth="3" />

            {/* FIR labels */}
            <text className="node-label" x="66" y="36" textAnchor="middle">MYSURU</text>
            <text className="node-label amount-sm" x="66" y="92" textAnchor="middle">₹21L</text>
            <text className="node-label" x="50" y="162" textAnchor="middle">MANGALURU</text>
            <text className="node-label amount-sm" x="50" y="220" textAnchor="middle">₹18L</text>
            <text className="node-label" x="66" y="288" textAnchor="middle">HUBBALLI</text>
            <text className="node-label amount-sm" x="66" y="344" textAnchor="middle">₹15L</text>

            {/* hub labels */}
            <text className="amount" x="196" y="150" textAnchor="middle">₹54L</text>
            <text className="node-label hub" x="196" y="226" textAnchor="middle">AGGREGATION HUB</text>
            <text className="node-label" x="196" y="239" textAnchor="middle">HDFC ••0001</text>

            {/* ring leader labels */}
            <text className="node-label lead" x="352" y="140" textAnchor="middle">RING LEADER</text>
            <text className="node-label name" x="352" y="230" textAnchor="middle">VICTOR HALE</text>
            <text className="node-label" x="352" y="243" textAnchor="middle">3 aliases · 3 districts</text>

            {/* alias labels */}
            <text className="node-label alias" x="424" y="70" textAnchor="middle">V. Hale</text>
            <text className="node-label alias" x="424" y="316" textAnchor="middle">Viktor Hall</text>
          </svg>
          <p className="hero-caption">
            <span className="hero-caption-tag">Example</span>
            FIRs from Three different districts resolve to one HDFC hub account holding <strong>₹54L</strong>,
            controlled by a single accused operating under <strong>3 aliases</strong>.
          </p>
        </div>
      </div>

      <PoweredBy />
    </div>
  );
}

const TECH_STACK: Array<{ name: string; note: string; logo: string }> = [
  { name: "Zoho Catalyst", note: "Serverless · Stratus · QuickML", logo: "/logos/zoho.svg" },
  { name: "Pinecone", note: "Vector search", logo: "/logos/pinecone.svg" },
  { name: "Neo4j", note: "Entity graph", logo: "/logos/neo4j.svg" },
  { name: "LangGraph", note: "Agent orchestration", logo: "/logos/langchain.svg" },
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
        Created by <strong>Team Radiant Rangers</strong> — Ankan Bera (
        <a href="mailto:eklapothik54@gmail.com">eklapothik54@gmail.com</a>)
      </p>
    </div>
  );
}

function ConsoleLayout() {
  return (
    <div className="console-shell">
      <aside className="sidebar contour">
        <Link to="/" className="brand-block">
          <img
            className="brand-lockup-image"
            src={aegisBrandImage}
            alt="Aegis Crime Analytics Assistant"
          />
        </Link>
        <nav className="sidebar-nav" aria-label="Main navigation">
          <NavLink
            to="/dashboard"
            className={({ isActive }) => `sidebar-link${isActive ? " active" : ""}`}
          >
            Overview
          </NavLink>
          <NavLink
            to="/ingest"
            className={({ isActive }) => `sidebar-link${isActive ? " active" : ""}`}
          >
            Ingest
          </NavLink>
          <NavLink
            to="/assistant"
            className={({ isActive }) => `sidebar-link${isActive ? " active" : ""}`}
          >
            Assistant
          </NavLink>
          <NavLink
            to="/admin"
            className={({ isActive }) => `sidebar-link${isActive ? " active" : ""}`}
          >
            Admin
          </NavLink>
        </nav>
        <div className="sidebar-foot">
          <strong>
            {FIXED_DEMO_USER.rank} {FIXED_DEMO_USER.name}
          </strong>
          <span>
            {FIXED_DEMO_USER.station} | {FIXED_DEMO_USER.kgid}
          </span>
        </div>
      </aside>
      <main className="main-panel">
        <Outlet />
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

  useEffect(() => {
    if (!runId || (run && TERMINAL_PIPELINE_STATUSES.has(run.status))) {
      return;
    }

    const ws = new WebSocket(buildPipelineWebSocketUrl(runId));
    ws.onmessage = (event) => {
      try {
        const payload = JSON.parse(event.data) as PipelineRun & { status?: string };
        if (payload.status === "NOT_FOUND") {
          return;
        }
        setRun(payload);
      } catch {
        setError("Failed to parse live pipeline update.");
      }
    };
    ws.onerror = () => {
      setError("Live pipeline socket disconnected. Using status polling fallback.");
    };

    return () => {
      ws.close();
    };
  }, [runId, run]);

  useEffect(() => {
    if (!runId || (run && TERMINAL_PIPELINE_STATUSES.has(run.status))) {
      return;
    }
    const timer = window.setInterval(() => {
      void getPipelineStatus(runId)
        .then((status) => {
          setRun(status);
        })
        .catch(() => {
          setError("Polling pipeline status failed.");
        });
    }, 5000);
    return () => {
      window.clearInterval(timer);
    };
  }, [runId, run]);

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
        <p className="kicker">Ingestion</p>
        <h2>Data ingestion</h2>
        <p className="page-subtitle">
          Select a prepared scenario to stage its FIR, then run the ingestion pipeline and monitor
          the current run.
        </p>
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
            {draftFiles.length} files staged | {(totalUploadBytes / (1024 * 1024)).toFixed(2)} MB total
          </p>

          <ul className="file-list">
            {draftFiles.map((entry) => (
              <li key={entry.id} className="file-row">
                <div className="file-meta">
                  <strong>{entry.file.name}</strong>
                  <span>{(entry.file.size / (1024 * 1024)).toFixed(2)} MB</span>
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

              {run.files_progress && Object.keys(run.files_progress).length > 0 && (
                <ul className="simple-list compact">
                  {Object.entries(run.files_progress).map(([fileName, progress]) => (
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
        <p className="kicker">Configuration</p>
        <h2>Admin</h2>
        <p className="page-subtitle">
          Set the entity review threshold and inspect how each FIR, IR and evidence schema maps
          extracted entities into SQL tables and graph objects.
        </p>
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

const TOOL_LABELS: Record<ToolKind, string> = {
  reason: "Reasoning",
  neo4j: "Neo4j",
  pinecone: "Pinecone",
  sql: "SQL",
  stratus: "Stratus",
};

function AssistantGraphView({ graph }: { graph: AssistantGraph }) {
  function nodeFor(id: string) {
    return graph.nodes.find((node) => node.id === id);
  }

  return (
    <div className="assistant-graph-card">
      <svg viewBox={`0 0 ${graph.width} ${graph.height}`} role="img" aria-label={graph.caption || "Assistant graph"}>
        {graph.edges.map((edge, index) => {
          const from = nodeFor(edge.from);
          const to = nodeFor(edge.to);
          if (!from || !to) {
            return null;
          }
          return (
            <line
              key={`${edge.from}-${edge.to}-${index}`}
              className={`assistant-edge ${edge.kind}`}
              x1={from.x}
              y1={from.y}
              x2={to.x}
              y2={to.y}
            />
          );
        })}
        {graph.nodes.map((node) => (
          <g key={node.id} className={`assistant-node ${node.kind}`}>
            {node.kind === "leader" && <circle className="assistant-node-halo" cx={node.x} cy={node.y} r="23" />}
            <circle cx={node.x} cy={node.y} r={node.kind === "leader" ? 23 : 17} />
            <text x={node.x} y={node.y + 34} textAnchor="middle">
              {node.label}
            </text>
            {node.sub && (
              <text className="node-sub" x={node.x} y={node.y + 48} textAnchor="middle">
                {node.sub}
              </text>
            )}
          </g>
        ))}
      </svg>
      {graph.caption && <p>{graph.caption}</p>}
    </div>
  );
}

function AssistantResponseView({ response }: { response: AssistantResponse }) {
  return (
    <div className="assistant-response">
      <div className="agent-trace">
        <div className="trace-title">Agent reasoning</div>
        {response.steps.map((step, index) => (
          <article key={step.id} className={`trace-step ${step.kind}`}>
            <span className="trace-step-index">{String(index + 1).padStart(2, "0")}</span>
            <div>
              <header>
                <span>{TOOL_LABELS[step.kind]}</span>
                <strong>{step.title}</strong>
              </header>
              {step.detail && <code>{step.detail}</code>}
              {step.output && <p>{step.output}</p>}
            </div>
          </article>
        ))}
      </div>

      <div className="assistant-answer">
        {response.answer.split("\n\n").map((paragraph) => (
          <p key={paragraph}>{paragraph}</p>
        ))}
      </div>

      {response.graph && <AssistantGraphView graph={response.graph} />}

      {response.citations && response.citations.length > 0 && (
        <div className="citation-panel">
          <div className="trace-title">Cited sources</div>
          {response.citations.map((citation, index) => (
            <a key={citation.id} className="citation-card" href={citation.href} target="_blank" rel="noreferrer">
              <span>[{index + 1}] {citation.label}</span>
              <code>{citation.source}</code>
              {citation.snippet && <small>{citation.snippet}</small>}
            </a>
          ))}
        </div>
      )}
    </div>
  );
}

function buildSeedHistory(scenario: DemoScenario): ChatMessage[] {
  const seedPrompt = scenario.prompts[0];
  const seeded = getScenarioResponse(scenario.id);
  const stamp = nowLabel();
  const intro: ChatMessage = {
    id: makeId("assistant"),
    role: "assistant",
    at: stamp,
    content: `Session ready for ${scenario.shortTitle}. Case context is attached — ask a question or use a prompt below.`,
  };
  if (!seedPrompt || !seeded) {
    return [intro];
  }
  return [
    intro,
    {
      id: makeId("user"),
      role: "user",
      at: stamp,
      content: seedPrompt.prompt,
    },
    {
      id: makeId("assistant"),
      role: "assistant",
      at: stamp,
      content: seeded.answer,
      response: seeded,
    },
  ];
}

function AssistantPage() {
  const [searchParams, setSearchParams] = useSearchParams();
  const [caseList, setCaseList] = useState<CaseSummary[]>([]);
  const [selectedCaseId, setSelectedCaseId] = useState<number | null>(null);
  const [selectedCaseDetail, setSelectedCaseDetail] = useState<CaseDetail | null>(null);
  const [activeScenarioId, setActiveScenarioId] = useState<string>(DEMO_SCENARIOS[0]?.id ?? "");
  const [messages, setMessages] = useState<ChatMessage[]>(() =>
    DEMO_SCENARIOS[0] ? buildSeedHistory(DEMO_SCENARIOS[0]) : [],
  );
  const [input, setInput] = useState<string>("");
  const [activePrompt, setActivePrompt] = useState<ScenarioPrompt | null>(
    () => DEMO_SCENARIOS[0]?.prompts[0] ?? null,
  );
  const [busy, setBusy] = useState<boolean>(false);
  const [error, setError] = useState<string | null>(null);
  const chatEndRef = useRef<HTMLDivElement | null>(null);

  const activeScenario = useMemo(
    () => DEMO_SCENARIOS.find((scenario) => scenario.id === activeScenarioId) ?? null,
    [activeScenarioId],
  );

  useEffect(() => {
    let cancelled = false;
    void listCases(200)
      .then((cases) => {
        if (cancelled) {
          return;
        }
        setCaseList(cases);
        const caseFromQuery = Number(searchParams.get("case"));
        if (!Number.isNaN(caseFromQuery) && caseFromQuery > 0) {
          setSelectedCaseId(caseFromQuery);
          return;
        }
        if (cases.length > 0) {
          setSelectedCaseId((current) => current ?? cases[0].case_master_id);
        }
      })
      .catch((loadErr) => {
        if (!cancelled) {
          setError(loadErr instanceof Error ? loadErr.message : "Failed to load case list.");
        }
      });
    return () => {
      cancelled = true;
    };
  }, []);

  useEffect(() => {
    const caseFromQuery = Number(searchParams.get("case"));
    if (Number.isNaN(caseFromQuery) || caseFromQuery <= 0) {
      return;
    }
    setSelectedCaseId((current) => (current === caseFromQuery ? current : caseFromQuery));
  }, [searchParams]);

  useEffect(() => {
    if (!selectedCaseId) {
      setSelectedCaseDetail(null);
      return;
    }
    let cancelled = false;
    void getCase(selectedCaseId)
      .then((detail) => {
        if (!cancelled) {
          setSelectedCaseDetail(detail);
        }
      })
      .catch((loadErr) => {
        if (!cancelled) {
          setError(loadErr instanceof Error ? loadErr.message : "Failed to load selected case.");
        }
      });
    return () => {
      cancelled = true;
    };
  }, [selectedCaseId]);

  useEffect(() => {
    chatEndRef.current?.scrollIntoView({ behavior: "smooth", block: "end" });
  }, [messages, busy]);

  function handleCaseSelect(caseId: number): void {
    setSelectedCaseId(caseId);
    setSearchParams({ case: String(caseId) });
  }

  function selectScenario(scenario: DemoScenario): void {
    setActiveScenarioId(scenario.id);
    setActivePrompt(scenario.prompts[0] ?? null);
    setInput(scenario.prompts[0]?.prompt ?? "");
    setMessages(buildSeedHistory(scenario));
    setError(null);
  }

  function applyScenarioPrompt(prompt: ScenarioPrompt): void {
    setActivePrompt(prompt);
    setInput(prompt.prompt);
  }

  async function sendMessage(event: FormEvent<HTMLFormElement>): Promise<void> {
    event.preventDefault();
    const trimmed = input.trim();
    if (!trimmed || busy) {
      return;
    }

    const userMessage: ChatMessage = {
      id: makeId("user"),
      role: "user",
      at: nowLabel(),
      content: trimmed,
    };
    setMessages((current) => [...current, userMessage]);
    setInput("");
    setBusy(true);
    setError(null);

    try {
      const response = await assistantClient.sendMessage({
        caseDetails: selectedCaseDetail,
        prompt: trimmed,
        scenarioId: activeScenario?.id,
        scenarioTitle: activeScenario?.title,
      });
      const assistantMessage: ChatMessage = {
        id: makeId("assistant"),
        role: "assistant",
        at: nowLabel(),
        content: response.answer,
        response,
      };
      setMessages((current) => [...current, assistantMessage]);
    } catch (sendErr) {
      setError(sendErr instanceof Error ? sendErr.message : "Failed to generate assistant response.");
    } finally {
      setBusy(false);
    }
  }

  return (
    <div className="page-wrap page-wrap-wide">
      <header className="page-head">
        <p className="kicker">Investigation</p>
        <h2>Assistant</h2>
        <p className="page-subtitle">
          Select a scenario, then ask questions about the case. The assistant shows its tool calls,
          reasoning, network graph, and cited sources.
        </p>
      </header>
      {error && <p className="alert alert-danger">{error}</p>}

      <section className="scenario-card-grid">
        {DEMO_SCENARIOS.map((scenario, index) => (
          <article
            key={scenario.id}
            className={`card scenario-card${activeScenarioId === scenario.id ? " active" : ""}`}
          >
            <span className="scenario-index">Scenario {String(index + 1).padStart(2, "0")}</span>
            <h3>{scenario.shortTitle}</h3>
            <p>{scenario.description}</p>
            <button
              className={activeScenarioId === scenario.id ? "btn btn-primary btn-sm" : "btn btn-ghost btn-sm"}
              type="button"
              onClick={() => selectScenario(scenario)}
            >
              {activeScenarioId === scenario.id ? "Active session" : "Open session"}
            </button>
          </article>
        ))}
      </section>

      <div className="assistant-layout">
        <aside className="card panel assistant-rail">
          <div className="section-headline">
            <h3>Case context</h3>
          </div>
          <label className="stack-label">
            Case
            <select
              value={selectedCaseId ?? ""}
              onChange={(event) => handleCaseSelect(Number(event.target.value))}
            >
              {caseList.length === 0 && <option value="">No cases loaded</option>}
              {caseList.map((caseItem) => (
                <option key={caseItem.case_master_id} value={caseItem.case_master_id}>
                  Case {caseItem.case_master_id} — {caseItem.crime_no || caseItem.case_no || "Unknown"}
                </option>
              ))}
            </select>
          </label>

          {selectedCaseDetail ? (
            <div className="case-detail">
              <p className="mono">ID {selectedCaseDetail.case_master_id}</p>
              <p>
                <span className="meta-label">Crime No</span>
                {selectedCaseDetail.crime_no || "N/A"}
              </p>
              <p>
                <span className="meta-label">Registered</span>
                {formatDate(selectedCaseDetail.crime_registered_date)}
              </p>
              <p className="muted small">
                {selectedCaseDetail.brief_facts || "No brief facts on file for this case."}
              </p>
            </div>
          ) : (
            <p className="muted small">Select a case to attach investigation context.</p>
          )}

          {activeScenario && (
            <>
              <div className="section-headline">
                <h3>Suggested prompts</h3>
              </div>
              <div className="chip-wrap">
                {activeScenario.prompts.map((prompt) => (
                  <button
                    key={prompt.id}
                    className={`chip-button${activePrompt?.id === prompt.id ? " active" : ""}`}
                    type="button"
                    onClick={() => applyScenarioPrompt(prompt)}
                  >
                    {prompt.label}
                  </button>
                ))}
              </div>
            </>
          )}
        </aside>

        <section className="card panel chat-panel">
          <div className="section-headline">
            <div>
              <h3>{activeScenario ? activeScenario.shortTitle : "Chat session"}</h3>
              <p className="section-sub">
                {messages.filter((m) => m.role === "user").length} officer messages ·{" "}
                {messages.filter((m) => m.role === "assistant" && m.response).length} agent replies
              </p>
            </div>
            <span className="status-pill neutral">Agent trace preview</span>
          </div>

          <div className="chat-window">
            {messages.length === 0 ? (
              <div className="chat-empty">
                <strong>No conversation yet</strong>
                <p>Select a scenario above to load a sample investigation thread.</p>
              </div>
            ) : (
              messages.map((message) => (
                <article
                  key={message.id}
                  className={`chat-bubble ${message.role === "assistant" ? "assistant" : "user"}`}
                >
                  <header>
                    <span>{message.role === "assistant" ? "Assistant" : "Officer"}</span>
                    {message.at && <time>{message.at}</time>}
                  </header>
                  {message.response ? (
                    <AssistantResponseView response={message.response} />
                  ) : (
                    <p>{message.content}</p>
                  )}
                </article>
              ))
            )}
            {busy && (
              <article className="chat-bubble assistant thinking">
                <header>
                  <span>Assistant</span>
                  <time>now</time>
                </header>
                <p className="thinking-line">Querying SQL · Neo4j · Pinecone…</p>
              </article>
            )}
            <div ref={chatEndRef} />
          </div>

          <form className="chat-form" onSubmit={(event) => void sendMessage(event)}>
            <label className="stack-label">
              Message
              <textarea
                value={input}
                onChange={(event) => setInput(event.target.value)}
                placeholder="Ask about timeline, money flow, alias links, or legal checklist."
                rows={3}
              />
            </label>
            <div className="action-row">
              <button className="btn btn-primary" type="submit" disabled={busy || !input.trim()}>
                {busy ? "Thinking…" : "Send"}
              </button>
              <button className="btn btn-ghost" type="button" onClick={() => setInput("")}>
                Clear
              </button>
            </div>
          </form>
        </section>
      </div>
    </div>
  );
}

export default App;
