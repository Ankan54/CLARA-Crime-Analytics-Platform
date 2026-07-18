import { useEffect, useMemo, useRef, useState } from "react";
import { useLocation, useNavigate, useNavigationType } from "react-router-dom";
import { DEMO_SCENARIOS, type DemoScenario } from "../../data/scenarios";
import { localizePrompt, uiText } from "../../data/assistantTranslations";
import { listCases, type CaseSummary } from "../../lib/api";
import { cancelAssistantRun, streamAssistantMessage, type AssistantRunHandle } from "../../lib/assistantClient";
import { FIXED_DEMO_USER } from "../../config/demoUser";
import type {
  AssistantAction,
  AssistantArtifact,
  AssistantEvent,
  AssistantLanguage,
  AssistantMessage,
  AssistantRunTrace,
  AssistantSession,
  AssistantTraceEvent,
} from "../../lib/assistantTypes";
import { ChatHistoryRail } from "./ChatHistoryRail";
import { AssistantTurn } from "./AssistantTurn";
import { SuggestedPrompts } from "./SuggestedPrompts";
import { ChatComposer } from "./ChatComposer";
import { ArtifactDrawer } from "./ArtifactDrawer";
import { AssistantTracePage } from "./AssistantTracePage";
import { AssistantIcon } from "./icons";
import { UserProfileMenu } from "../UserProfileMenu";
import { useToast } from "../ToastProvider";

const SESSIONS_KEY = "aegis.assistant.sessions.v2";
const LEGACY_SESSIONS_KEY = "aegis.assistant.sessions.v1";
const COLLAPSED_KEY = "aegis.assistant.history-collapsed";

function makeId(prefix: string): string {
  return `${prefix}-${Date.now()}-${Math.random().toString(16).slice(2, 8)}`;
}

function nowLabel(): string {
  return new Date().toLocaleTimeString([], { hour: "2-digit", minute: "2-digit" });
}

function nowIso(): string {
  return new Date().toISOString();
}

function isAssistantLanguage(value: string | null | undefined): value is AssistantLanguage {
  return value === "en" || value === "hi" || value === "kn";
}

function deriveTitle(promptText: string): string {
  const trimmed = promptText.trim();
  return trimmed.length > 48 ? `${trimmed.slice(0, 48)}…` : trimmed;
}

function introContent(language: AssistantLanguage, scenario: DemoScenario | null, crimeNo?: string, caseId?: number | null): string {
  const suffix = [crimeNo ? `CrimeNo: ${crimeNo}` : null, caseId ? `Case ID: ${caseId}` : null]
    .filter(Boolean)
    .join(" · ");
  if (language === "hi") {
    return scenario
      ? `${scenario.shortTitle} के लिए सेशन तैयार है। संदर्भ केस लोड है — नीचे सुझाए गए प्रश्नों से शुरू करें।${suffix ? ` (${suffix})` : ""}`
      : `सेशन तैयार है। संदर्भ चुनें या सीधे सवाल पूछें।${suffix ? ` (${suffix})` : ""}`;
  }
  if (language === "kn") {
    return scenario
      ? `${scenario.shortTitle}ಗಾಗಿ ಸೆಷನ್ ಸಿದ್ಧವಾಗಿದೆ. ಕೇಸ್ ಸಂದರ್ಭ ಲೋಡ್ ಆಗಿದೆ — ಕೆಳಗಿನ ಸೂಚಿಸಿದ ಪ್ರಶ್ನೆಗಳಿಂದ ಆರಂಭಿಸಿ.${suffix ? ` (${suffix})` : ""}`
      : `ಸೆಷನ್ ಸಿದ್ಧವಾಗಿದೆ. ಸಂದರ್ಭ ಆಯ್ಕೆಮಾಡಿ ಅಥವಾ ನೇರವಾಗಿ ಪ್ರಶ್ನೆ ಕೇಳಿ.${suffix ? ` (${suffix})` : ""}`;
  }
  return scenario
    ? `Session ready for ${scenario.shortTitle}. Case context is attached — ask a question or use a suggested prompt below.${suffix ? ` (${suffix})` : ""}`
    : `Session ready. Select context or ask a free-form question.${suffix ? ` (${suffix})` : ""}`;
}

function createSession(options: {
  scenario?: DemoScenario | null;
  language: AssistantLanguage;
  crimeNo?: string;
  caseId?: number | null;
}): AssistantSession {
  const { scenario, language, crimeNo, caseId } = options;
  const shouldAddIntro = Boolean(scenario || crimeNo || caseId);
  const intro: AssistantMessage[] = shouldAddIntro
    ? [
        {
          id: makeId("assistant"),
          role: "assistant",
          content: introContent(language, scenario ?? null, crimeNo, caseId),
          status: "complete",
          at: nowLabel(),
        },
      ]
    : [];
  const createdAt = nowIso();
  return {
    id: makeId("session"),
    title: scenario ? scenario.shortTitle : "New session",
    scenarioId: scenario?.id,
    crimeNo: crimeNo ?? scenario?.crimeNo,
    caseId: caseId ?? null,
    language,
    activeRunId: undefined,
    updatedAt: createdAt,
    messages: intro,
    traces: [],
  };
}

function normalizeSession(raw: unknown): AssistantSession | null {
  if (!raw || typeof raw !== "object") return null;
  const input = raw as Record<string, unknown>;
  if (typeof input.id !== "string") return null;
  const scenario = typeof input.scenarioId === "string"
    ? DEMO_SCENARIOS.find((item) => item.id === input.scenarioId) ?? null
    : null;
  const language = isAssistantLanguage(input.language as string | undefined) ? input.language as AssistantLanguage : "en";
  const messages = Array.isArray(input.messages) ? (input.messages as AssistantMessage[]) : [];
  return {
    id: input.id,
    title: typeof input.title === "string" ? input.title : "New session",
    scenarioId: scenario?.id,
    crimeNo: typeof input.crimeNo === "string" ? input.crimeNo : scenario?.crimeNo,
    caseId: typeof input.caseId === "number" ? input.caseId : null,
    language,
    activeRunId: typeof input.activeRunId === "string" ? input.activeRunId : undefined,
    updatedAt: typeof input.updatedAt === "string" ? input.updatedAt : nowIso(),
    messages,
    traces: Array.isArray(input.traces) ? (input.traces as AssistantRunTrace[]) : [],
  };
}

function loadSessions(initialLanguage: AssistantLanguage): AssistantSession[] {
  try {
    const modern = window.localStorage.getItem(SESSIONS_KEY);
    const parsedModern = modern ? (JSON.parse(modern) as unknown[]) : [];
    const normalizedModern = Array.isArray(parsedModern)
      ? parsedModern.map(normalizeSession).filter((item): item is AssistantSession => Boolean(item))
      : [];
    if (normalizedModern.length > 0) {
      return normalizedModern;
    }
    const legacy = window.localStorage.getItem(LEGACY_SESSIONS_KEY);
    const parsedLegacy = legacy ? (JSON.parse(legacy) as unknown[]) : [];
    const normalizedLegacy = Array.isArray(parsedLegacy)
      ? parsedLegacy.map(normalizeSession).filter((item): item is AssistantSession => Boolean(item))
      : [];
    if (normalizedLegacy.length > 0) {
      return normalizedLegacy.map((session) => ({ ...session, language: session.language ?? initialLanguage }));
    }
    return [];
  } catch {
    return [];
  }
}

function loadCollapsed(): boolean {
  try {
    return JSON.parse(window.localStorage.getItem(COLLAPSED_KEY) ?? "false") === true;
  } catch {
    return false;
  }
}

function applyEvent(message: AssistantMessage, event: AssistantEvent): AssistantMessage {
  switch (event.type) {
    case "run_started":
      return { ...message, runId: event.run_id };
    case "step": {
      const steps = message.steps ? [...message.steps] : [];
      const index = steps.findIndex((step) => step.id === event.step.id);
      if (index >= 0) {
        // Preserve code/retrieval already streamed onto this step if the new step
        // payload doesn't carry them (common for status-only updates).
        const prev = steps[index];
        steps[index] = {
          ...event.step,
          code: event.step.code ?? prev.code,
          retrieval: event.step.retrieval ?? prev.retrieval,
        };
      } else {
        steps.push(event.step);
      }
      return { ...message, steps };
    }
    case "answer_delta":
      return { ...message, content: message.content + event.delta };
    case "artifact":
      return { ...message, artifacts: [...(message.artifacts ?? []), event.artifact] };
    case "retrieval": {
      const steps = message.steps ? [...message.steps] : [];
      const stepId = event.retrieval.stepId;
      const index = stepId ? steps.findIndex((step) => step.id === stepId) : -1;
      if (index >= 0) {
        steps[index] = { ...steps[index], retrieval: event.retrieval };
      }
      return { ...message, steps };
    }
    case "code": {
      const steps = message.steps ? [...message.steps] : [];
      const stepId = event.code.stepId;
      const index = stepId ? steps.findIndex((step) => step.id === stepId) : -1;
      const statusFromPhase =
        event.code.phase === "error" || event.code.success === false
          ? "error"
          : event.code.phase === "done"
            ? "done"
            : "running";
      if (index >= 0) {
        steps[index] = {
          ...steps[index],
          code: event.code,
          status: event.code.phase === "template" ? steps[index].status : statusFromPhase,
        };
      } else if (stepId) {
        // Streaming template phase can arrive before a tool_call step exists -- upsert one.
        steps.push({
          id: stepId,
          agent: "supervisor",
          kind: "tool_call",
          title: event.code.phase === "template" ? "Writing Python" : "Running Python",
          status: statusFromPhase,
          toolName: "run_python",
          code: event.code,
        });
      }
      return { ...message, steps };
    }
    case "plan":
      return { ...message, plan: event.plan };
    case "action":
      return { ...message, actions: [...(message.actions ?? []), event.action] };
    case "citation":
      return { ...message, citations: [...(message.citations ?? []), event.citation] };
    case "done":
      return { ...message, status: "complete" };
    case "error":
      return { ...message, status: "error", error: event.message };
    default:
      return message;
  }
}

function summarizeEvent(event: AssistantEvent): string {
  switch (event.type) {
    case "run_started":
      return "Run started";
    case "step":
      return `${event.step.agent.toUpperCase()} · ${event.step.title} (${event.step.status})`;
    case "answer_delta":
      return `Answer stream (${event.delta.length} chars)`;
    case "artifact":
      return `Artifact ready: ${event.artifact.title}`;
    case "retrieval":
      return `Retrieval: ${event.retrieval.count} result(s)`;
    case "code":
      return `Code ${event.code.phase}`;
    case "plan":
      return `Plan: ${event.plan.tasks.length} task(s)`;
    case "action":
      return `Follow-up action: ${event.action.label}`;
    case "citation":
      return `Citation attached: ${event.citation.label}`;
    case "done":
      return "Run completed";
    case "error":
      return `Error: ${event.message}`;
    default:
      return "Event";
  }
}

function sanitizeTracePayload(event: AssistantEvent): unknown {
  if (event.type === "artifact") {
    return {
      ...event,
      artifact: {
        id: event.artifact.id,
        kind: event.artifact.kind,
        title: event.artifact.title,
        mimeType: "mimeType" in event.artifact ? event.artifact.mimeType : undefined,
        caption: event.artifact.caption,
      },
    };
  }
  return event;
}

function appendTraceEvent(trace: AssistantRunTrace, event: AssistantEvent): AssistantRunTrace {
  const timestamp = nowIso();
  if (event.type === "answer_delta" && trace.events.length > 0) {
    const last = trace.events[trace.events.length - 1];
    if (last.type === "answer_delta") {
      const previousPayload = last.payload as { run_id: string; type: "answer_delta"; delta: string };
      const mergedPayload: Extract<AssistantEvent, { type: "answer_delta" }> = {
        ...previousPayload,
        delta: previousPayload.delta + event.delta,
      };
      const mergedEvent: AssistantTraceEvent = {
        ...last,
        at: timestamp,
        summary: `Answer stream (${mergedPayload.delta.length} chars)`,
        payload: mergedPayload,
      };
      return {
        ...trace,
        updatedAt: timestamp,
        events: [...trace.events.slice(0, -1), mergedEvent],
      };
    }
  }
  const traceEvent: AssistantTraceEvent = {
    id: makeId("trace"),
    runId: event.run_id,
    seq: trace.events.length + 1,
    at: timestamp,
    type: event.type,
    summary: summarizeEvent(event),
    payload: sanitizeTracePayload(event),
  };
  return {
    ...trace,
    updatedAt: timestamp,
    events: [...trace.events, traceEvent],
  };
}

function readLanguageFromUrl(): AssistantLanguage {
  const params = new URLSearchParams(window.location.search);
  const requested = params.get("lang");
  return isAssistantLanguage(requested) ? requested : "en";
}

export function AssistantPage() {
  const toast = useToast();
  const location = useLocation();
  const navigate = useNavigate();
  const navigationType = useNavigationType();
  const initialLanguage = readLanguageFromUrl();
  const initialSessions = loadSessions(initialLanguage);
  const [sessions, setSessions] = useState<AssistantSession[]>(
    initialSessions.length > 0 ? initialSessions : [createSession({ language: initialLanguage })],
  );
  const [activeSessionId, setActiveSessionId] = useState<string>(() => {
    const params = new URLSearchParams(window.location.search);
    const requested = params.get("session");
    if (requested && initialSessions.some((session) => session.id === requested)) {
      return requested;
    }
    return initialSessions[0]?.id ?? "";
  });
  const [historyCollapsed, setHistoryCollapsed] = useState<boolean>(loadCollapsed);
  const [input, setInput] = useState("");
  const [busy, setBusy] = useState(false);
  const [resolvingContext, setResolvingContext] = useState(false);
  const [caseOptions, setCaseOptions] = useState<CaseSummary[]>([]);
  const [drawerArtifact, setDrawerArtifact] = useState<AssistantArtifact | null>(null);
  // What the officer just picked in the Scenario dropdown, shown immediately. Selecting
  // a scenario is async (resolveCaseId hits the backend) and swaps in a brand-new
  // session once it resolves -- the select's value is otherwise bound to
  // activeScenario?.id, which doesn't change until that new session exists. In between,
  // setResolvingContext(true) forces a re-render where the select is still bound to the
  // OLD session's scenario, so the DOM snapped back to the previous option (and the
  // select disables at the same instant) -- reported live as "flickering, and the
  // scenario isn't getting selected." Tracking the pick locally makes the dropdown
  // reflect the officer's choice the instant they make it, independent of how long
  // resolution takes.
  const [pendingScenarioId, setPendingScenarioId] = useState<string | null>(null);
  const [scenarioMenuOpen, setScenarioMenuOpen] = useState(false);
  const scenarioMenuRef = useRef<HTMLDivElement | null>(null);
  // Holds the live run so Stop can reach it, and so a new message detaches the old
  // stream before starting another.
  const runRef = useRef<AssistantRunHandle | null>(null);
  const scrollAnchorRef = useRef<HTMLDivElement | null>(null);
  const turnsRef = useRef<HTMLDivElement | null>(null);
  const stickToBottomRef = useRef(true);

  const activeSession = sessions.find((session) => session.id === activeSessionId) ?? sessions[0] ?? null;
  const activeLanguage: AssistantLanguage = activeSession?.language ?? "en";
  const copy = uiText(activeLanguage);
  const activeScenario = activeSession?.scenarioId
    ? DEMO_SCENARIOS.find((scenario) => scenario.id === activeSession.scenarioId) ?? null
    : null;

  const traceRunId = useMemo(() => {
    const marker = "/assistant/trace/";
    if (!location.pathname.startsWith(marker)) {
      return null;
    }
    return decodeURIComponent(location.pathname.slice(marker.length));
  }, [location.pathname]);

  const traceCarrier = useMemo(
    () =>
      sessions.find((session) => (session.traces ?? []).some((trace) => trace.runId === traceRunId)) ?? null,
    [sessions, traceRunId],
  );

  const selectedTrace = useMemo(
    () => traceCarrier?.traces?.find((trace) => trace.runId === traceRunId) ?? null,
    [traceCarrier, traceRunId],
  );

  const localizedPrompts = useMemo(
    () => (activeScenario?.prompts ?? []).map((prompt) => localizePrompt(prompt, activeLanguage)),
    [activeScenario, activeLanguage],
  );

  const caseSelectValue = useMemo(() => {
    if (!activeSession) return "";
    if (activeSession.caseId != null) {
      return `case:${activeSession.caseId}`;
    }
    if (activeSession.crimeNo) {
      return `crime:${activeSession.crimeNo}`;
    }
    return "";
  }, [activeSession]);

  const hasTrace = Boolean(activeSession?.activeRunId);

  useEffect(() => {
    if (!scenarioMenuOpen) {
      return;
    }
    // Attach on next tick so the opening click doesn't immediately close, and so
    // native <select> option picks (which can land outside the popover DOM) still
    // fire onChange before we tear the menu down.
    const attachId = window.setTimeout(() => {
      function onPointerDown(event: PointerEvent) {
        const root = scenarioMenuRef.current;
        if (!root || root.contains(event.target as Node)) {
          return;
        }
        window.setTimeout(() => setScenarioMenuOpen(false), 0);
      }
      function onKey(event: KeyboardEvent) {
        if (event.key === "Escape") {
          setScenarioMenuOpen(false);
        }
      }
      document.addEventListener("pointerdown", onPointerDown);
      document.addEventListener("keydown", onKey);
      cleanup = () => {
        document.removeEventListener("pointerdown", onPointerDown);
        document.removeEventListener("keydown", onKey);
      };
    }, 0);
    let cleanup: (() => void) | undefined;
    return () => {
      window.clearTimeout(attachId);
      cleanup?.();
    };
  }, [scenarioMenuOpen]);

  useEffect(() => {
    let cancelled = false;
    // Backend caps limit at 200 (Query(..., le=200) in routers/cases.py) -- 250 here
    // 422'd on every load, silently leaving the case-context picker empty (confirmed
    // live via read_network_requests). 200 matches the working call site in App.tsx.
    void listCases(200)
      .then((items) => {
        if (!cancelled) {
          setCaseOptions(items);
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

  // Deep-link from scenario briefings: /assistant?scenario=<id> creates a session
  // for that demo once on mount (does not re-fire when the officer later clears context).
  const bootstrappedScenarioRef = useRef(false);
  useEffect(() => {
    if (bootstrappedScenarioRef.current) {
      return;
    }
    const requested = new URLSearchParams(location.search).get("scenario");
    if (!requested || !DEMO_SCENARIOS.some((item) => item.id === requested)) {
      return;
    }
    bootstrappedScenarioRef.current = true;
    if (activeSession?.scenarioId === requested) {
      return;
    }
    void handleSelectScenario(requested);
    // eslint-disable-next-line react-hooks/exhaustive-deps -- mount bootstrap only
  }, []);

  useEffect(() => {
    if (traceCarrier && traceCarrier.id !== activeSessionId) {
      setActiveSessionId(traceCarrier.id);
    }
  }, [traceCarrier, activeSessionId]);

  useEffect(() => {
    window.localStorage.setItem(SESSIONS_KEY, JSON.stringify(sessions));
  }, [sessions]);

  useEffect(() => {
    window.localStorage.setItem(COLLAPSED_KEY, JSON.stringify(historyCollapsed));
  }, [historyCollapsed]);

  useEffect(() => {
    if (stickToBottomRef.current) {
      scrollAnchorRef.current?.scrollIntoView({ behavior: "auto", block: "end" });
    }
  }, [activeSession?.messages, busy, traceRunId]);

  useEffect(() => () => runRef.current?.close(), []);

  // `activeSession` deliberately excluded from deps below -- see the comment inside the
  // array: including the object itself (not just its primitive fields) is the bug this
  // effect used to have, not a fix this rule should suggest.
  useEffect(() => { // eslint-disable-line react-hooks/exhaustive-deps
    if (!activeSession) return;
    const params = new URLSearchParams(location.search);
    params.set("session", activeSession.id);
    params.set("lang", activeSession.language);
    if (activeSession.scenarioId) params.set("scenario", activeSession.scenarioId);
    else params.delete("scenario");
    if (activeSession.crimeNo) params.set("crime", activeSession.crimeNo);
    else params.delete("crime");
    const next = params.toString();
    const current = location.search.startsWith("?") ? location.search.slice(1) : location.search;
    if (next !== current) {
      navigate({ pathname: location.pathname, search: `?${next}` }, { replace: true });
    }
    // Deliberately NOT depending on `activeSession` itself, only its primitive fields
    // below (which the effect body actually reads). `sessions` -- and therefore
    // `activeSession = sessions.find(...)` -- gets a brand-new object reference on every
    // setSessions call, including the ones streamed WS events trigger on every step/
    // answer_delta while a run is live. With the object in the deps, this effect refired
    // on every one of those (even though id/language/scenarioId/crimeNo hadn't changed),
    // calling navigate()/history.replaceState() dozens of times a second -- Chrome's IPC
    // flood protection then throttled navigation entirely, which is what made the
    // scenario picker appear to flicker and never actually select anything.
  }, [
    activeSession?.id,
    activeSession?.language,
    activeSession?.scenarioId,
    activeSession?.crimeNo,
    location.pathname,
    location.search,
    navigate,
  ]);

  // Only resync state FROM the URL on a POP (browser back/forward, or the initial
  // page load -- react-router classifies that as POP too). The effect above pushes
  // state TO the URL via navigate(..., {replace:true}), which is async: on the render
  // right after a session click, `location.search` here still reflects the OLD url
  // for one more tick. Without this guard, this effect read that stale url, decided
  // the just-updated activeSessionId didn't match, and reverted it -- which flipped
  // activeSession?.id again, so the effect above navigated again, forever. Confirmed
  // live: clicking a session in the left rail produced 2000+ renders/sec alternating
  // between the two session ids, which is also what was tripping Chrome's IPC flood
  // protection ("Throttling navigation...") and reading as UI flicker.
  useEffect(() => {
    if (navigationType !== "POP") return;
    const params = new URLSearchParams(location.search);
    const sessionId = params.get("session");
    if (sessionId && sessions.some((session) => session.id === sessionId) && sessionId !== activeSessionId) {
      setActiveSessionId(sessionId);
    }
  }, [location.search, sessions, activeSessionId, navigationType]);

  useEffect(() => {
    if (!activeSessionId && sessions[0]) {
      setActiveSessionId(sessions[0].id);
    }
  }, [activeSessionId, sessions]);

  function handleTurnsScroll(): void {
    const el = turnsRef.current;
    if (!el) return;
    const distanceFromBottom = el.scrollHeight - el.scrollTop - el.clientHeight;
    stickToBottomRef.current = distanceFromBottom < 96;
  }

  function patchSession(sessionId: string, updater: (session: AssistantSession) => AssistantSession): void {
    setSessions((current) =>
      current.map((session) => (session.id === sessionId ? updater(session) : session)),
    );
  }

  function handleNewChat(): void {
    const session = createSession({
      language: activeLanguage,
      scenario: activeScenario,
      crimeNo: activeSession?.crimeNo,
      caseId: activeSession?.caseId,
    });
    setSessions((current) => [session, ...current]);
    setActiveSessionId(session.id);
    setDrawerArtifact(null);
    stickToBottomRef.current = true;
  }

  async function resolveCaseId(crimeNo: string): Promise<number | null> {
    const exactLocal = caseOptions.find((item) => item.crime_no === crimeNo);
    if (exactLocal) {
      return exactLocal.case_master_id;
    }
    const searched = await listCases(20, crimeNo);
    const exactRemote = searched.find((item) => item.crime_no === crimeNo);
    if (!exactRemote) {
      return null;
    }
    setCaseOptions((current) => {
      if (current.some((item) => item.case_master_id === exactRemote.case_master_id)) return current;
      return [exactRemote, ...current];
    });
    return exactRemote.case_master_id;
  }

  async function handleSelectScenario(scenarioId: string): Promise<void> {
    // Set before anything async so the select shows the pick on this render, not a
    // future one -- see the state's own comment for why that matters here.
    setPendingScenarioId(scenarioId);
    if (!scenarioId) {
      const session = createSession({ language: activeLanguage });
      setSessions((current) => [session, ...current]);
      setActiveSessionId(session.id);
      setDrawerArtifact(null);
      setPendingScenarioId(null);
      return;
    }
    const scenario = DEMO_SCENARIOS.find((item) => item.id === scenarioId);
    if (!scenario) {
      setPendingScenarioId(null);
      return;
    }
    setResolvingContext(true);
    try {
      const caseId = await resolveCaseId(scenario.crimeNo);
      const session = createSession({
        scenario,
        language: activeLanguage,
        crimeNo: scenario.crimeNo,
        caseId,
      });
      setSessions((current) => [session, ...current]);
      setActiveSessionId(session.id);
      setDrawerArtifact(null);
      setInput("");
    } catch (resolveError) {
      toast.error(resolveError instanceof Error ? resolveError.message : "Failed to resolve scenario context.");
    } finally {
      setResolvingContext(false);
      setPendingScenarioId(null);
    }
  }

  function handleSelectCaseContext(nextValue: string): void {
    if (!activeSession) return;
    if (!nextValue) {
      patchSession(activeSession.id, (session) => ({
        ...session,
        scenarioId: undefined,
        crimeNo: undefined,
        caseId: null,
        updatedAt: nowIso(),
      }));
      return;
    }
    if (nextValue.startsWith("crime:")) {
      const crimeNo = nextValue.slice("crime:".length);
      const scenario = DEMO_SCENARIOS.find((item) => item.crimeNo === crimeNo);
      patchSession(activeSession.id, (session) => ({
        ...session,
        scenarioId: scenario?.id,
        crimeNo,
        caseId: null,
        updatedAt: nowIso(),
      }));
      return;
    }
    const caseId = Number(nextValue.slice("case:".length));
    const matchedCase = caseOptions.find((item) => item.case_master_id === caseId);
    const crimeNo = matchedCase?.crime_no ?? activeSession.crimeNo;
    const scenario = crimeNo ? DEMO_SCENARIOS.find((item) => item.crimeNo === crimeNo) ?? null : null;
    patchSession(activeSession.id, (session) => ({
      ...session,
      scenarioId: scenario?.id,
      caseId,
      crimeNo,
      updatedAt: nowIso(),
    }));
  }

  function handleLanguageChange(nextLanguage: AssistantLanguage): void {
    if (!activeSession || nextLanguage === activeSession.language) return;
    if (activeSession.messages.length > 0) {
      const scenario = activeSession.scenarioId
        ? DEMO_SCENARIOS.find((item) => item.id === activeSession.scenarioId) ?? null
        : null;
      const session = createSession({
        scenario,
        language: nextLanguage,
        caseId: activeSession.caseId,
        crimeNo: activeSession.crimeNo,
      });
      setSessions((current) => [session, ...current]);
      setActiveSessionId(session.id);
      setDrawerArtifact(null);
      setInput("");
      return;
    }
    patchSession(activeSession.id, (session) => ({ ...session, language: nextLanguage, updatedAt: nowIso() }));
  }

  function handleSelectSession(id: string): void {
    setActiveSessionId(id);
    setDrawerArtifact(null);
    stickToBottomRef.current = true;
  }

  function handleDeleteSession(id: string): void {
    const next = sessions.filter((session) => session.id !== id);
    const finalSessions = next.length > 0 ? next : [createSession({ language: activeLanguage })];
    setSessions(finalSessions);
    if (activeSessionId === id) {
      setActiveSessionId(finalSessions[0].id);
      setDrawerArtifact(null);
    }
  }

  async function sendMessage(promptText: string, promptId?: string): Promise<void> {
    const trimmed = promptText.trim();
    if (!trimmed || busy || !activeSession) {
      return;
    }

    runRef.current?.close();
    runRef.current = null;
    stickToBottomRef.current = true;

    const sessionId = activeSession.id;
    const userMessage: AssistantMessage = { id: makeId("user"), role: "user", content: trimmed, at: nowLabel() };
    const assistantMessageId = makeId("assistant");
    const placeholder: AssistantMessage = {
      id: assistantMessageId,
      role: "assistant",
      content: "",
      status: "streaming",
      steps: [],
      artifacts: [],
      actions: [],
      citations: [],
      at: nowLabel(),
    };

    setSessions((current) =>
      current.map((session) =>
        session.id === sessionId
          ? {
              ...session,
              title: session.title === "New session" ? deriveTitle(trimmed) : session.title,
              updatedAt: nowIso(),
              messages: [...session.messages, userMessage, placeholder],
            }
          : session,
      ),
    );
    setInput("");
    setBusy(true);

    function handleEvent(event: AssistantEvent): void {
      setSessions((current) =>
        current.map((session) => {
          if (session.id !== sessionId) return session;
          const updatedMessages = session.messages.map((message) =>
            message.id === assistantMessageId ? applyEvent(message, event) : message,
          );
          const runId = event.run_id;
          const existingTraces = [...(session.traces ?? [])];
          const traceIndex = existingTraces.findIndex((trace) => trace.runId === runId);
          const baseTrace: AssistantRunTrace =
            traceIndex >= 0
              ? existingTraces[traceIndex]
              : {
                  runId,
                  language: session.language,
                  prompt: trimmed,
                  promptId,
                  status: "streaming",
                  startedAt: nowIso(),
                  updatedAt: nowIso(),
                  events: [],
                };
          const withEvent = appendTraceEvent(baseTrace, event);
          const status: AssistantRunTrace["status"] =
            event.type === "done" ? "complete" : event.type === "error" ? "error" : "streaming";
          const nextTrace = { ...withEvent, status };
          const mergedTraces =
            traceIndex >= 0
              ? existingTraces.map((trace, index) => (index === traceIndex ? nextTrace : trace))
              : [nextTrace, ...existingTraces];
          return {
            ...session,
            messages: updatedMessages,
            activeRunId: runId,
            traces: mergedTraces,
            updatedAt: nowIso(),
          };
        }),
      );
      if (event.type === "done") {
        setBusy(false);
        runRef.current = null;
      } else if (event.type === "error") {
        setBusy(false);
        toast.error(event.message);
        runRef.current = null;
      }
    }

    try {
      runRef.current = await streamAssistantMessage(
        {
          prompt: trimmed,
          promptId,
          caseId: activeSession.caseId ?? null,
          crimeNo: activeSession.crimeNo,
          scenarioKey: activeSession.scenarioId,
          scenarioTitle: activeScenario?.title,
          // The backend adopts this id (upsert), so the local session and the persisted
          // one stay the same conversation across reloads.
          sessionId: activeSession.id,
          userId: String(FIXED_DEMO_USER.employeeId),
          language: activeSession.language,
        },
        handleEvent,
      );
    } catch (sendErr) {
      setBusy(false);
      toast.error(sendErr instanceof Error ? sendErr.message : "Assistant request failed.");
    }
  }

  /** Stop the run server-side. It still ends with a normal `done`, so the UI unwinds
   *  through the same path as a completed turn. */
  function handleStop(): void {
    const run = runRef.current;
    if (!run) return;
    void cancelAssistantRun(run.runId);
  }

  function handleAction(action: AssistantAction): void {
    void sendMessage(action.prompt, action.promptId);
  }

  function openTrace(): void {
    if (!activeSession?.activeRunId) return;
    navigate({
      pathname: `/assistant/trace/${encodeURIComponent(activeSession.activeRunId)}`,
      search: location.search,
    });
  }

  function closeTrace(): void {
    navigate({ pathname: "/assistant", search: location.search });
  }

  return (
    <div className="assistant-shell">
      <ChatHistoryRail
        sessions={sessions}
        activeSessionId={activeSession?.id ?? ""}
        collapsed={historyCollapsed}
        sessionsLabel={copy.sessions}
        newChatLabel={copy.newChat}
        onSelect={handleSelectSession}
        onNew={handleNewChat}
        onDelete={handleDeleteSession}
        onToggleCollapsed={() => setHistoryCollapsed((current) => !current)}
      />

      <div className="assistant-main">
        <header className="assistant-topbar">
          <div className="assistant-topbar-title">
            <p className="kicker">Investigation</p>
            <h2>{activeSession?.title ?? "Assistant"}</h2>
          </div>
          <div className="assistant-topbar-controls">
            <label className="assistant-select-stack assistant-language-select">
              <span>{copy.language}</span>
              <select
                className="scenario-dropdown"
                value={activeLanguage}
                onChange={(event) => handleLanguageChange(event.target.value as AssistantLanguage)}
                disabled={busy}
              >
                <option value="en">English</option>
                <option value="hi">Hindi</option>
                <option value="kn">Kannada</option>
              </select>
            </label>
            <div
              className={`assistant-context-menu${scenarioMenuOpen ? " is-open" : ""}`}
              ref={scenarioMenuRef}
            >
              <button
                type="button"
                className="btn btn-ghost"
                aria-expanded={scenarioMenuOpen}
                aria-haspopup="dialog"
                onClick={() => setScenarioMenuOpen((open) => !open)}
              >
                <AssistantIcon name="panel" />
                {activeScenario?.shortTitle ?? copy.selectScenario}
              </button>
              {scenarioMenuOpen ? (
                <div className="assistant-context-popover" role="dialog" aria-label={copy.selectScenario}>
                  <label className="assistant-select-stack">
                    <span>{copy.selectScenario}</span>
                    <select
                      className="scenario-dropdown"
                      value={pendingScenarioId ?? activeScenario?.id ?? ""}
                      onChange={(event) => {
                        setScenarioMenuOpen(false);
                        void handleSelectScenario(event.target.value);
                      }}
                      disabled={busy || resolvingContext}
                    >
                      <option value="">{copy.freeForm}</option>
                      {DEMO_SCENARIOS.map((scenario) => (
                        <option key={scenario.id} value={scenario.id}>
                          {scenario.shortTitle} — {scenario.ingestHook}
                        </option>
                      ))}
                    </select>
                  </label>
                  <label className="assistant-select-stack">
                    <span>{copy.caseContext}</span>
                    <select
                      className="scenario-dropdown"
                      value={caseSelectValue}
                      onChange={(event) => {
                        setScenarioMenuOpen(false);
                        handleSelectCaseContext(event.target.value);
                      }}
                      disabled={busy || resolvingContext}
                    >
                      <option value="">No case selected</option>
                      {activeScenario && (
                        <option value={`crime:${activeScenario.crimeNo}`}>
                          {activeScenario.crimeNo}
                          {activeSession?.caseId == null ? " · Not ingested yet" : " · Scenario default"}
                        </option>
                      )}
                      {caseOptions.map((caseSummary) => (
                        <option key={caseSummary.case_master_id} value={`case:${caseSummary.case_master_id}`}>
                          Case {caseSummary.case_master_id} · {caseSummary.crime_no || caseSummary.case_no || "Unknown"}
                        </option>
                      ))}
                    </select>
                  </label>
                </div>
              ) : null}
            </div>
            <button
              type="button"
              className="btn btn-ghost assistant-trace-open"
              onClick={openTrace}
              disabled={!hasTrace}
              title={hasTrace ? copy.showTraces : copy.showTracesHint}
            >
              <AssistantIcon name="history" />
              {copy.showTraces}
            </button>
            <UserProfileMenu />
          </div>
        </header>

        {traceRunId ? (
          <div className="assistant-trace-wrap">
            <AssistantTracePage
              trace={selectedTrace}
              runId={traceRunId}
              language={activeLanguage}
              onBack={closeTrace}
            />
          </div>
        ) : (
          <>
            <div className="assistant-turns" ref={turnsRef} onScroll={handleTurnsScroll}>
              {(!activeSession || activeSession.messages.length === 0) && (
                <div className="chat-empty">
                  <strong>{copy.noConversationTitle}</strong>
                  <p>{copy.noConversationBody}</p>
                </div>
              )}
              {activeSession?.messages.map((message) => (
                <AssistantTurn
                  key={message.id}
                  message={message}
                  onOpenArtifact={setDrawerArtifact}
                  onAction={handleAction}
                  onRetry={message.status === "error" ? () => {
                    const msgs = activeSession?.messages ?? [];
                    const prevUser = msgs.slice(0, msgs.indexOf(message)).reverse().find((m: typeof message) => m.role === "user");
                    if (prevUser) sendMessage(prevUser.content);
                  } : undefined}
                  activeArtifactId={drawerArtifact?.id}
                  busy={busy}
                />
              ))}
              <div ref={scrollAnchorRef} />
            </div>

            <div className="assistant-composer-dock">
              <SuggestedPrompts
                prompts={localizedPrompts}
                title={copy.suggestedQuestions}
                onSelect={(prompt) => void sendMessage(prompt.prompt, prompt.id)}
                disabled={busy}
              />
              <ChatComposer
                value={input}
                onChange={setInput}
                placeholder={copy.composerPlaceholder}
                onSend={() => void sendMessage(input)}
                onStop={handleStop}
                busy={busy || resolvingContext}
                language={activeLanguage}
              />
            </div>
          </>
        )}
      </div>

      <ArtifactDrawer artifact={drawerArtifact} onClose={() => setDrawerArtifact(null)} />
    </div>
  );
}
