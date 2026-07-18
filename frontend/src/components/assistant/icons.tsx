export type AssistantIconName =
  | "mic"
  | "send"
  | "chevron-down"
  | "chevron-left"
  | "chevron-right"
  | "panel"
  | "close"
  | "plus"
  | "link"
  | "graph"
  | "legal"
  | "trend"
  | "download"
  | "fit"
  | "table"
  | "document"
  | "history";

const common = {
  width: 16,
  height: 16,
  viewBox: "0 0 24 24",
  fill: "none",
  stroke: "currentColor",
  strokeWidth: 1.8,
  strokeLinecap: "round" as const,
  strokeLinejoin: "round" as const,
};

/** One inline-SVG icon set for the assistant UI, keyed by name (mirrors the `FeatureIcon` pattern in App.tsx). */
export function AssistantIcon({ name, className }: { name: AssistantIconName; className?: string }) {
  const props = { ...common, className };
  switch (name) {
    case "mic":
      return (
        <svg {...props}>
          <rect x="9" y="3" width="6" height="11" rx="3" />
          <path d="M5 11a7 7 0 0 0 14 0" />
          <line x1="12" y1="18" x2="12" y2="22" />
          <line x1="8" y1="22" x2="16" y2="22" />
        </svg>
      );
    case "send":
      return (
        <svg {...props}>
          <line x1="21" y1="3" x2="10" y2="14" />
          <polygon points="21 3 14.5 21 10 14 3 9.5 21 3" />
        </svg>
      );
    case "chevron-down":
      return (
        <svg {...props}>
          <polyline points="6 9 12 15 18 9" />
        </svg>
      );
    case "chevron-left":
      return (
        <svg {...props}>
          <polyline points="15 18 9 12 15 6" />
        </svg>
      );
    case "chevron-right":
      return (
        <svg {...props}>
          <polyline points="9 18 15 12 9 6" />
        </svg>
      );
    case "panel":
      return (
        <svg {...props}>
          <rect x="3" y="4" width="18" height="16" rx="2" />
          <line x1="9" y1="4" x2="9" y2="20" />
        </svg>
      );
    case "close":
      return (
        <svg {...props}>
          <line x1="6" y1="6" x2="18" y2="18" />
          <line x1="18" y1="6" x2="6" y2="18" />
        </svg>
      );
    case "plus":
      return (
        <svg {...props}>
          <line x1="12" y1="5" x2="12" y2="19" />
          <line x1="5" y1="12" x2="19" y2="12" />
        </svg>
      );
    case "link":
      return (
        <svg {...props}>
          <path d="M9 15 15 9" />
          <path d="M10 6l1-1a4 4 0 0 1 6 6l-1 1" />
          <path d="M14 18l-1 1a4 4 0 0 1-6-6l1-1" />
        </svg>
      );
    case "graph":
      return (
        <svg {...props}>
          <circle cx="6" cy="6" r="2.4" />
          <circle cx="18" cy="7" r="2.4" />
          <circle cx="12" cy="17" r="2.4" />
          <path d="M8 7l8 0.6M7.4 8.2 10.8 15M16.6 9 13.2 15" />
        </svg>
      );
    case "legal":
      return (
        <svg {...props}>
          <path d="M12 3v18" />
          <path d="M5 7l-3 6a3 3 0 0 0 6 0z" />
          <path d="M19 7l-3 6a3 3 0 0 0 6 0z" />
          <path d="M5 7h14" />
          <path d="M8 21h8" />
        </svg>
      );
    case "trend":
      return (
        <svg {...props}>
          <polyline points="3 17 9 11 13 15 21 5" />
          <polyline points="15 5 21 5 21 11" />
        </svg>
      );
    case "download":
      return (
        <svg {...props}>
          <path d="M12 3v12" />
          <polyline points="7 11 12 16 17 11" />
          <path d="M5 19h14" />
        </svg>
      );
    case "fit":
      return (
        <svg {...props}>
          <polyline points="9 3 3 3 3 9" />
          <polyline points="15 3 21 3 21 9" />
          <polyline points="9 21 3 21 3 15" />
          <polyline points="15 21 21 21 21 15" />
        </svg>
      );
    case "table":
      return (
        <svg {...props}>
          <rect x="3" y="4" width="18" height="16" rx="1.5" />
          <line x1="3" y1="10" x2="21" y2="10" />
          <line x1="9" y1="4" x2="9" y2="20" />
        </svg>
      );
    case "document":
      return (
        <svg {...props}>
          <path d="M7 4h7l4 4v12H7z" />
          <path d="M14 4v4h4M9.5 13h5M9.5 16h5" />
        </svg>
      );
    case "history":
      return (
        <svg {...props}>
          <circle cx="12" cy="12" r="8.5" />
          <polyline points="12 8 12 12 15 14" />
        </svg>
      );
    default:
      return null;
  }
}
