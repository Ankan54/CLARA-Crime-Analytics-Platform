export type LandingGraphNodeTone = "money" | "hub" | "alias" | "leader";
export type LandingGraphEdgeTone = "money" | "control" | "alias";

export type LandingGraphNode = {
  id: string;
  x: number;
  y: number;
  r: number;
  tone: LandingGraphNodeTone;
  pulseClass?: string;
  halo?: boolean;
  fill?: string;
};

export type LandingGraphEdge = {
  from: string;
  to: string;
  tone: LandingGraphEdgeTone;
};

export type LandingGraphText = {
  x: number;
  y: number;
  value: string;
  className: string;
  anchor?: "start" | "middle" | "end";
};

export type LandingHeroSlide = {
  id: string;
  title: string;
  ariaLabel: string;
  caption: string;
  nodes: LandingGraphNode[];
  edges: LandingGraphEdge[];
  texts: LandingGraphText[];
};

export const LANDING_HERO_SLIDES: LandingHeroSlide[] = [
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

export function getHeroSlide(scenarioId: string): LandingHeroSlide | undefined {
  return LANDING_HERO_SLIDES.find((slide) => slide.id === scenarioId);
}

export function nodeStrokeColor(tone: LandingGraphNodeTone): string {
  if (tone === "hub" || tone === "leader") {
    return "#f7c948";
  }
  if (tone === "alias") {
    return "#8b7cff";
  }
  return "#35e0ff";
}

export function nodeStrokeWidth(tone: LandingGraphNodeTone): number {
  if (tone === "leader") {
    return 3;
  }
  if (tone === "hub") {
    return 2.4;
  }
  return 2;
}

export function nodeFillColor(node: LandingGraphNode): string {
  if (node.fill) {
    return node.fill;
  }
  return node.tone === "leader" ? "#141003" : "#0b1020";
}
