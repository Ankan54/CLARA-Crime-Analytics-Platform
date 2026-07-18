import type { UploadFileType } from "../lib/api";

export interface ScenarioPrompt {
  id: string;
  label: string;
  prompt: string;
}

export interface ScenarioDocument {
  name: string;
  /** Vite-resolved URL from src/assets/live_demo. */
  path: string;
  fileType: UploadFileType;
  label: string;
}

export type BriefingFindingVisual =
  | { kind: "heroGraph" }
  | { kind: "metricStrip"; items: { label: string; value: string }[] }
  | { kind: "callout"; tone: "wow" | "amber" | "info"; text: string }
  | { kind: "stepList"; title: string; steps: string[] }
  | { kind: "aliasCollapse"; aliases: string[]; resolvedAs: string }
  | { kind: "surgeBars"; weeks: { label: string; count: number }[] };

export type BriefingChapter = {
  id: string;
  title: string;
  body: string;
  visual?: BriefingFindingVisual;
  documentNames?: string[];
};

export type ScenarioBriefing = {
  persona: string;
  victimLoss: string;
  primaryWow: string;
  accent: "cyan" | "violet" | "green" | "magenta";
  hook: string;
  metrics: { label: string; value: string }[];
  chapters: BriefingChapter[];
};

export interface DemoScenario {
  id: string;
  title: string;
  shortTitle: string;
  description: string;
  ingestHook: string;
  liveKey: string;
  crimeNo: string;
  documents: ScenarioDocument[];
  prompts: ScenarioPrompt[];
  briefing: ScenarioBriefing;
}

// Single source of truth: src/assets/live_demo (no public/scenarios copies).
const assetUrls = import.meta.glob(
  [
    "../assets/live_demo/live_scn*/fir.txt",
    "../assets/live_demo/live_scn*/investigation_report.txt",
    "../assets/live_demo/evidence/**/*",
  ],
  { query: "?url", import: "default", eager: true },
) as Record<string, string>;

function asset(rel: string): string {
  const key = `../assets/live_demo/${rel}`;
  const url = assetUrls[key];
  if (!url) throw new Error(`Missing scenario asset: ${rel}`);
  return url;
}

export const DEMO_SCENARIOS: DemoScenario[] = [
  {
    id: "digital-arrest",
    title: "Scenario 1 - Digital Arrest",
    shortTitle: "Digital Arrest",
    description: "Cross-district digital arrest scam ring with fast money movement analysis.",
    ingestHook: "3 district FIRs → 1 HDFC hub account (₹54L in ~2 hours).",
    liveKey: "scn1",
    crimeNo: "129011001202690001",
    documents: [
      { name: "fir.txt", path: asset("live_scn1/fir.txt"), fileType: "fir", label: "FIR · Bengaluru CEN" },
      { name: "investigation_report.txt", path: asset("live_scn1/investigation_report.txt"), fileType: "ir", label: "IR · Investigation Report" },
      { name: "call_log.csv", path: asset("evidence/scenario_1/evidence/call_log.csv"), fileType: "evidence", label: "Evidence · Call Log" },
      { name: "transaction_ledger.csv", path: asset("evidence/scenario_1/evidence/transaction_ledger.csv"), fileType: "evidence", label: "Evidence · Transaction Ledger" },
      { name: "messaging_screenshot_1.html", path: asset("evidence/scenario_1/evidence/messaging_screenshot_1.html"), fileType: "evidence", label: "Evidence · Messaging Screenshot" },
    ],
    prompts: [
      { id: "s1-timeline", label: "Build timeline", prompt: "Summarise this case and lay out the timeline of events and transfers." },
      { id: "s1-money-speed", label: "Money speed", prompt: "Where did the money go and how fast did it move across accounts?" },
      { id: "s1-similar-mo", label: "Similar MO", prompt: "Has this modus operandi appeared in other districts in Karnataka?" },
      { id: "s1-links", label: "Find links", prompt: "Find links among the related cases and show shared accounts or devices." },
      { id: "s1-legal-gaps", label: "Legal gaps", prompt: "Is this prosecutable now, and what evidence gaps must be closed first?" },
    ],
    briefing: {
      persona: "Station IO · Cyber PS, Bengaluru",
      victimLoss: "Dr. Anand Rao, 58 · ₹42 lakh",
      primaryWow: "Four districts, one playbook — one shared hub account",
      accent: "cyan",
      hook: "A single Bengaluru digital-arrest complaint looks local and hopeless. Money velocity, MO matching across districts, and a shared aggregation account turn it into the thread that unravels a four-district ring.",
      metrics: [
        { label: "Live loss", value: "₹42L" },
        { label: "Districts linked", value: "4" },
        { label: "Hub pool", value: "₹54L" },
        { label: "Still freezable", value: "~₹9.3L" },
      ],
      chapters: [
        {
          id: "complaint",
          title: "The complaint",
          body: "A retired professor in Malleswaram is held on a fake TRAI-to-CBI video call, told he is under “digital arrest,” and frightened into moving savings into what he believes is an RBI verification escrow. Three UPI transfers later, the callers vanish. On paper it is one station’s cyber fraud FIR — high loss, thin leads, and a mule account that looks like a dead end.",
          documentNames: ["fir.txt"],
        },
        {
          id: "findings",
          title: "First findings",
          body: "From the live case alone the platform rebuilds the ordeal as a timed sequence — call start, coerced transfers, silence — then walks the money outward hop by hop. Velocity analysis flags accounts that took inflow with no onward outflow: funds still sitting, still actionable in the golden hour, not just a post-mortem trail.",
          visual: {
            kind: "stepList",
            title: "What surfaces first",
            steps: [
              "Case timeline of the two-day custody call and transfers",
              "Time-ordered money path from the victim account outward",
              "Freezable-funds set: last-in with no later outbound",
            ],
          },
          documentNames: ["call_log.csv", "transaction_ledger.csv"],
        },
        {
          id: "link",
          title: "The link that changes everything",
          body: "Vector search over FIR narratives finds near-identical scripts in Mysuru, Mangaluru, and Hubballi — different names, phones, and surface accounts, same playbook. Graph search across those four crimes then collapses onto one shared aggregation hub. Four “separate” investigations become one operation.",
          visual: { kind: "heroGraph" },
        },
        {
          id: "reveal",
          title: "Evidence lands · the reveal",
          body: "When the investigation report and supporting evidence land — bank KYC, seized-phone identifiers, messaging captures — the graph redraws. Mule KYC names the collection layer; controller IMEI and UPI attach a previously unnamed ringleader; centrality ranks who actually runs the ring. The hub is no longer an anonymous sink.",
          visual: {
            kind: "callout",
            tone: "wow",
            text: "Controller identifiers emerge live — IMEI 8675…016 and UPI raghu.ctrl@ybl — and sit at the top of the ring by centrality.",
          },
          documentNames: ["investigation_report.txt", "messaging_screenshot_1.html"],
        },
        {
          id: "act",
          title: "Ready to act",
          body: "Legal traversal against BNS §§318/319 and IT §§66C/66D shows most elements supported. Amber remains where it matters for filing: chat screenshots still need BSA §63 certificates and hashes, and the controller link must be evidenced tightly before charge sheets go out. The Assistant’s legal-gap prompts are built for exactly that checklist.",
          visual: {
            kind: "callout",
            tone: "amber",
            text: "Fix §63 on messaging evidence and harden the controller link before filing — a 2024 SC acquittal hinged on the missing-certificate gap.",
          },
        },
      ],
    },
  },
  {
    id: "many-names",
    title: "Scenario 2 - Many Names, One Man",
    shortTitle: "Many Names, One Man",
    description: "Alias resolution, repeat offender profiling, and escalation over time.",
    ingestHook: "One accused, three aliases — escalating ₹1.5L → ₹8L.",
    liveKey: "scn2",
    crimeNo: "129011005202690002",
    documents: [
      { name: "fir.txt", path: asset("live_scn2/fir.txt"), fileType: "fir", label: "FIR · repeat offender" },
      { name: "investigation_report.txt", path: asset("live_scn2/investigation_report.txt"), fileType: "ir", label: "IR · Investigation Report" },
      { name: "bsa_63_certificate.txt", path: asset("evidence/scenario_2/evidence/bsa_63_certificate.txt"), fileType: "evidence", label: "Evidence · BSA 63 Certificate" },
      { name: "device_forensics.txt", path: asset("evidence/scenario_2/evidence/device_forensics.txt"), fileType: "evidence", label: "Evidence · Device Forensics" },
      { name: "messaging_screenshot_1.html", path: asset("evidence/scenario_2/evidence/messaging_screenshot_1.html"), fileType: "evidence", label: "Evidence · Messaging Screenshot" },
    ],
    prompts: [
      { id: "s2-known-accused", label: "Known accused check", prompt: "Do we already know this accused under other names or identifiers?" },
      { id: "s2-alias-collapse", label: "Alias collapse", prompt: "Show the alias resolution evidence and confidence factors." },
      { id: "s2-escalation", label: "Escalation history", prompt: "Show the offender history timeline and escalation in amount and severity." },
      { id: "s2-cdr-update", label: "CDR update", prompt: "Incorporate new CDR and account evidence and update the network view." },
      { id: "s2-intent-gap", label: "Intent proof gap", prompt: "What is missing to prove dishonest intent at inception under BNS 318?" },
    ],
    briefing: {
      persona: "Station IO · CEN PS",
      victimLoss: "Kavitha Reddy, 34 · ₹15 lakh",
      primaryWow: "Four aliases collapse into one known offender",
      accent: "violet",
      hook: "The accused arrives as a chat handle and a first name. Shared IMEI, UPI, and phone collapse spelling variants into one escalating repeat offender — and show he is not working alone.",
      metrics: [
        { label: "Live loss", value: "₹15L" },
        { label: "Aliases → 1", value: "4 → 1" },
        { label: "Shared keys", value: "IMEI · UPI · phone" },
        { label: "Escalation", value: "2024 → 2026" },
      ],
      chapters: [
        {
          id: "complaint",
          title: "The complaint",
          body: "A software engineer is drawn into a high-return investment pitch — WhatsApp group, persuasive caller, UPI payout path — and loses ₹15 lakh when the handler goes dark. The FIR names “Imran S.” That string alone is almost useless for matching across the corpus.",
          documentNames: ["fir.txt"],
        },
        {
          id: "findings",
          title: "First findings",
          body: "Entity resolution does not stop at the name. Exact identifier blocks on IMEI, UPI, and phone, plus fuzzy name matching, surface prior person records with high confidence. The officer sees proof factors — not an opaque score — for why this live complaint likely belongs to someone already known.",
          visual: {
            kind: "callout",
            tone: "info",
            text: "Likely the same person as prior records — shared device + UPI shown as evidence, confidence readable per factor.",
          },
          documentNames: ["device_forensics.txt"],
        },
        {
          id: "link",
          title: "The link that changes everything",
          body: "Spelling variants across cases — Imran S., Imraan S., I. Shaikh, Imran Shek — resolve to one identity. The offender history timeline then tells the real story: smaller frauds in 2024–25 escalating into a ₹15L investment hit in 2026, with an operating footprint across Bengaluru and nearby districts.",
          visual: {
            kind: "aliasCollapse",
            aliases: ["Imran S.", "Imraan S.", "I. Shaikh", "Imran Shek"],
            resolvedAs: "Imran Sheikh",
          },
        },
        {
          id: "reveal",
          title: "Evidence lands · the reveal",
          body: "Investigation report, device forensics, messaging captures, and a BSA §63 certificate expand the graph. New phones in CDR share the same IMEI; additional victims attach. The picture shifts from lone scammer to a recruiter node inside a larger recruitment cluster.",
          visual: {
            kind: "stepList",
            title: "Escalation arc",
            steps: [
              "2024 — smaller loan-app / OTP-style frauds",
              "2025 — job and mid-value scams",
              "2026 — ₹15L investment scam (this FIR)",
              "IR update — cluster grows beyond a single victim",
            ],
          },
          documentNames: ["investigation_report.txt", "bsa_63_certificate.txt", "messaging_screenshot_1.html"],
        },
        {
          id: "act",
          title: "Ready to act",
          body: "For BNS §318 cheating, deception, inducement, and delivery look supportable. The weak point is dishonest intent at inception — strengthen with fabricated-profit artefacts and prior identical conduct now visible on the graph. Chat evidence still needs a proper §63 path. Ask the Assistant for the intent-gap checklist before filing.",
          visual: {
            kind: "callout",
            tone: "amber",
            text: "Intent-at-inception is amber — precedents show acquittals when that element is thin, even when money movement is clear.",
          },
        },
      ],
    },
  },
  {
    id: "follow-money",
    title: "Scenario 3 - Follow The Money",
    shortTitle: "Follow The Money",
    description: "Layering analysis, bridge account detection, and PMLA readiness checks.",
    ingestHook: "Victim → bridge → 5 mules → crypto; ₹6.2L still freezable.",
    liveKey: "scn3",
    crimeNo: "129191018202690003",
    documents: [
      { name: "fir.txt", path: asset("live_scn3/fir.txt"), fileType: "fir", label: "FIR · money laundering" },
      { name: "investigation_report.txt", path: asset("live_scn3/investigation_report.txt"), fileType: "ir", label: "IR · Investigation Report" },
      { name: "account_details.txt", path: asset("evidence/scenario_3/evidence/account_details.txt"), fileType: "evidence", label: "Evidence · Account Details" },
      { name: "bsa_63_certificate.txt", path: asset("evidence/scenario_3/evidence/bsa_63_certificate.txt"), fileType: "evidence", label: "Evidence · BSA 63 Certificate" },
      { name: "transaction_ledger.csv", path: asset("evidence/scenario_3/evidence/transaction_ledger.csv"), fileType: "evidence", label: "Evidence · Transaction Ledger" },
    ],
    prompts: [
      { id: "s3-trace", label: "Trace money", prompt: "Trace the money path end-to-end and highlight still-freezable funds." },
      { id: "s3-bridge", label: "Bridge account", prompt: "Find mule accounts connected to other crimes or scam categories." },
      { id: "s3-ledger-kyc", label: "Ledger + KYC update", prompt: "Process the bank transaction dump and KYC, then rank hub accounts." },
      { id: "s3-pmla", label: "PMLA readiness", prompt: "Can we add money laundering charges now, and what legal risks remain?" },
    ],
    briefing: {
      persona: "Cyber-Financial Cell IO · Dharwad",
      victimLoss: "Sandeep Traders (MSME) · ₹28 lakh",
      primaryWow: "One mule account bridges two scam types",
      accent: "green",
      hook: "₹28 lakh leaves an MSME and seems to vanish in minutes. Time-ordered layering rebuilds the path — and one bridge account ties this UPI fraud to a different crime family’s plumbing.",
      metrics: [
        { label: "Live loss", value: "₹28L" },
        { label: "Still freezable", value: "₹6.2L" },
        { label: "Bridge A/c", value: "..9001" },
        { label: "Hub KYC", value: "Somashekar T" },
      ],
      chapters: [
        {
          id: "complaint",
          title: "The complaint",
          body: "A Dharwad textile MSME is steered into a fake trading platform by someone posing as an advisor. Funds move into a collection account, then appear gone. The officer needs more than “follow the money” as a slogan — they need hops, timestamps, and accounts that can still be frozen.",
          documentNames: ["fir.txt"],
        },
        {
          id: "findings",
          title: "First findings",
          body: "Graph traversal rebuilds the laundering path in time order: collection into aggregation layers, fan-out across mule accounts, then cash-out and a crypto leg. Minute-level gaps expose rapid layering. Downstream accounts with last-in and no outbound are named as freezable now — roughly ₹6.2L still recoverable in this demo trail.",
          visual: {
            kind: "stepList",
            title: "Layering path",
            steps: [
              "Victim / collection intake",
              "Aggregation hops (sub-₹1L splits, minutes apart)",
              "Mule fan-out across the ring",
              "Cash-out + USDT wallet endpoint",
              "₹6.2L flagged freezable downstream",
            ],
          },
          documentNames: ["transaction_ledger.csv"],
        },
        {
          id: "link",
          title: "The link that changes everything",
          body: "Checking each mule against the wider corpus surfaces a bridge: the same account also touches a Belagavi digital-arrest trail. Two investigations that looked unrelated share laundering infrastructure. That is the cross-scam wow — and why a single station cannot see the full picture alone.",
          visual: { kind: "heroGraph" },
        },
        {
          id: "reveal",
          title: "Evidence lands · the reveal",
          body: "Bank dump, account details, and §63-backed records complete the transaction graph. PageRank elevates the busiest aggregation hub; KYC names the hub operator. Dormant-then-burst mule patterns — old open dates, idle history, sudden inflow — reinforce that this is engineered plumbing, not random transfers.",
          visual: {
            kind: "callout",
            tone: "wow",
            text: "Hub account ..9002 (KYC: Somashekar T) ranks #1 — the messy ledger becomes a hierarchy of who to pursue.",
          },
          documentNames: ["investigation_report.txt", "account_details.txt", "bsa_63_certificate.txt"],
        },
        {
          id: "act",
          title: "Ready to act",
          body: "Predicate offence and proceeds trail support a PMLA conversation. Amber risk sits on conspiracy knowledge for mules and any cash-out beneficiary still untraced — mere credit without proof of knowledge has failed in precedent. Use the Assistant’s PMLA readiness prompt before expanding charges.",
          visual: {
            kind: "callout",
            tone: "amber",
            text: "PMLA is not automatic: mule knowledge / conspiracy proof is still the fragile element.",
          },
        },
      ],
    },
  },
  {
    id: "surge",
    title: "Scenario 4 - The Surge",
    shortTitle: "The Surge",
    description: "Emerging pattern detection, hotspot analysis, and ring takedown planning.",
    ingestHook: "14 micro-FIRs → 7 shared mules → 1 controller device.",
    liveKey: "scn4",
    crimeNo: "129011002202690004",
    documents: [
      { name: "fir.txt", path: asset("live_scn4/fir.txt"), fileType: "fir", label: "FIR · task-job scam" },
      { name: "investigation_report.txt", path: asset("live_scn4/investigation_report.txt"), fileType: "ir", label: "IR · Investigation Report" },
      { name: "bsa_63_certificate.txt", path: asset("evidence/scenario_4/evidence/bsa_63_certificate.txt"), fileType: "evidence", label: "Evidence · BSA 63 Certificate" },
      { name: "device_pool.csv", path: asset("evidence/scenario_4/evidence/device_pool.csv"), fileType: "evidence", label: "Evidence · Device Pool" },
      { name: "messaging_screenshot_1.html", path: asset("evidence/scenario_4/evidence/messaging_screenshot_1.html"), fileType: "evidence", label: "Evidence · Messaging Screenshot" },
    ],
    prompts: [
      { id: "s4-pattern", label: "Pattern alert", prompt: "Is this FIR part of an emerging scam pattern in the last few weeks?" },
      { id: "s4-organized", label: "Organized ring check", prompt: "Is this surge coordinated by one ring or just independent copycats?" },
      { id: "s4-hotspots", label: "Hotspots and base", prompt: "Show district hotspots and likely operator co-location from shared IP data." },
      { id: "s4-org-chart", label: "Org chart", prompt: "Use seized device data to build the operator org chart and role map." },
      { id: "s4-operator-checklist", label: "Operator legal checklist", prompt: "What evidence checklist does each operator need before filing charges?" },
    ],
    briefing: {
      persona: "Cyber Cell IO · Bengaluru City",
      victimLoss: "Arjun K, 21 (student) · ₹3.5 lakh",
      primaryWow: "A scattered surge resolves into one organised ring",
      accent: "magenta",
      hook: "A routine student task-scam complaint is the leading edge of a 21-day wave. Spike detection and shared device/IP infrastructure collapse many small FIRs into one cell — with a roster ready to task across stations.",
      metrics: [
        { label: "Live loss", value: "₹3.5L" },
        { label: "Cluster window", value: "21 days" },
        { label: "Similar FIRs", value: "~19" },
        { label: "Operators", value: "~7" },
      ],
      chapters: [
        {
          id: "complaint",
          title: "The complaint",
          body: "An engineering student is groomed through Telegram “easy tasks,” small payouts, then rising deposits to unlock withdrawals — until the operators disappear. Loss is ₹3.5 lakh. Alone, it looks like one more micro-FIR in a noisy week.",
          documentNames: ["fir.txt"],
        },
        {
          id: "findings",
          title: "First findings",
          body: "Near-duplicate narrative clustering plus weekly case counts fire an emerging-pattern alert: roughly nineteen similar task-scam FIRs and tens of lakhs in combined loss inside a short window — a forming wave before it has an official label.",
          visual: {
            kind: "surgeBars",
            weeks: [
              { label: "Week 1", count: 3 },
              { label: "Week 2", count: 7 },
              { label: "Week 3", count: 9 },
            ],
          },
        },
        {
          id: "link",
          title: "The link that changes everything",
          body: "Community detection over shared IMEIs, operator IPs, and mule accounts collapses the scatter into one dense community. Victims are spread; operators co-locate — Electronic City IP blocks in this demo. Copycats become a coordinated ring with a probable controller.",
          visual: { kind: "heroGraph" },
        },
        {
          id: "reveal",
          title: "Evidence lands · the reveal",
          body: "A seized handler device dump supplies the org chart: callers, recruiters, mule handlers, and a controller UPI. Device-pool and messaging evidence tie roles to infrastructure. One ₹3.5L complaint becomes a multi-station tasking map.",
          visual: {
            kind: "stepList",
            title: "Operator roster (from device dump)",
            steps: [
              "Callers — front-line victim contact",
              "Recruiters — intake into the task funnel",
              "Mule handlers — payout / deposit rails",
              "Controller — UPI ring.ctrl04@ybl + hub account",
            ],
          },
          documentNames: [
            "investigation_report.txt",
            "device_pool.csv",
            "messaging_screenshot_1.html",
            "bsa_63_certificate.txt",
          ],
        },
        {
          id: "act",
          title: "Ready to act",
          body: "Charges map per operator role under BNS and IT provisions, with organised-crime consideration on the table. Shared infrastructure and script evidence are strong; amber remains on tying each operator to specific victims and completing §63 for the device dump. The Assistant’s per-operator checklist is the hand-off into filing.",
          visual: {
            kind: "callout",
            tone: "amber",
            text: "Per-operator files still need victim-specific ties and §63 coverage on the dump before coordinated charge sheets.",
          },
        },
      ],
    },
  },
];

export function getScenarioById(id: string): DemoScenario | undefined {
  return DEMO_SCENARIOS.find((scenario) => scenario.id === id);
}
