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
  },
];
