import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import ForceGraph2DImport from "react-force-graph-2d";
import type { GraphArtifact, GraphArtifactNode } from "../../lib/assistantTypes";
import { AssistantIcon } from "./icons";

// ponytail: react-force-graph-2d's .d.ts double-wraps its own generics in a way
// that fights plain JSX usage for no real benefit here. Treat it as untyped and
// keep our own local interfaces for the node/link shapes we hand it -- if this
// ever needs stricter checking, add a narrow local .d.ts override instead.
const ForceGraph2D = ForceGraph2DImport as any;

interface RuntimeNode {
  id: string;
  label: string;
  type: string;
  properties?: Record<string, string | number>;
  x?: number;
  y?: number;
}

interface RuntimeLink {
  source: string | RuntimeNode;
  target: string | RuntimeNode;
  relationship: string;
  properties?: Record<string, string | number>;
}

const NODE_PALETTE = [
  "var(--accent-strong)",
  "var(--ok)",
  "var(--warn)",
  "var(--danger)",
  "var(--graph-violet)",
  "var(--graph-cyan)",
  "var(--graph-magenta)",
  "var(--graph-green)",
];

function readCssVar(variableName: string, fallback: string): string {
  if (typeof window === "undefined") return fallback;
  const value = window.getComputedStyle(document.documentElement).getPropertyValue(variableName).trim();
  return value || fallback;
}

function useElementSize<T extends HTMLElement>() {
  const ref = useRef<T | null>(null);
  const [size, setSize] = useState({ width: 0, height: 0 });
  useEffect(() => {
    const el = ref.current;
    if (!el) return;
    const observer = new ResizeObserver((entries) => {
      const entry = entries[0];
      if (!entry) return;
      const { width, height } = entry.contentRect;
      setSize({ width, height });
    });
    observer.observe(el);
    return () => observer.disconnect();
  }, []);
  return { ref, size };
}

/** Interactive, Neo4j-Aura-style force graph with a "Results overview" side panel. */
export function GraphArtifactView({ artifact }: { artifact: GraphArtifact }) {
  const palette = useMemo(
    () =>
      NODE_PALETTE.map((value) =>
        value.startsWith("var(")
          ? readCssVar(value.replace("var(", "").replace(")", ""), "#60a5fa")
          : value,
      ),
    [],
  );

  const graphBackground = useMemo(() => readCssVar("--surface-inset", "#0d131c"), []);
  const textColor = useMemo(() => readCssVar("--text", "#f5f7fa"), []);
  const lineColor = useMemo(() => readCssVar("--border-strong", "rgba(255,255,255,0.35)"), []);
  const subduedTextColor = useMemo(() => readCssVar("--text-dim", "rgba(227,229,232,0.62)"), []);

  const { ref: containerRef, size } = useElementSize<HTMLDivElement>();
  const fgRef = useRef<any>(null);
  const [selectedId, setSelectedId] = useState<string | null>(null);

  const nodeTypeCounts = useMemo(() => {
    const map = new Map<string, number>();
    artifact.nodes.forEach((node) => map.set(node.type, (map.get(node.type) ?? 0) + 1));
    return map;
  }, [artifact]);

  const relationshipCounts = useMemo(() => {
    const map = new Map<string, number>();
    artifact.links.forEach((link) => map.set(link.relationship, (map.get(link.relationship) ?? 0) + 1));
    return map;
  }, [artifact]);

  const colorForType = useMemo(() => {
    const types = Array.from(nodeTypeCounts.keys()).sort();
    const map = new Map<string, string>();
    types.forEach((type, index) => map.set(type, palette[index % palette.length]));
    return map;
  }, [nodeTypeCounts, palette]);

  const graphData = useMemo(
    () => ({
      nodes: artifact.nodes.map<RuntimeNode>((node) => ({
        id: node.id,
        label: node.label,
        type: node.type,
        properties: node.properties,
      })),
      links: artifact.links.map<RuntimeLink>((link) => ({
        source: link.source,
        target: link.target,
        relationship: link.relationship,
        properties: link.properties,
      })),
    }),
    [artifact],
  );

  const selectedNode = useMemo<GraphArtifactNode | null>(
    () => artifact.nodes.find((node) => node.id === selectedId) ?? null,
    [artifact, selectedId],
  );

  const paintNode = useCallback(
    (node: RuntimeNode, ctx: CanvasRenderingContext2D, globalScale: number) => {
      const isSelected = selectedId === node.id;
      const radius = isSelected ? 9 : 6.5;
      const color = colorForType.get(node.type) ?? NODE_PALETTE[0];

      ctx.beginPath();
      ctx.arc(node.x ?? 0, node.y ?? 0, radius, 0, 2 * Math.PI);
      ctx.fillStyle = color;
      ctx.fill();
      ctx.lineWidth = (isSelected ? 2.4 : 1.3) / globalScale;
      ctx.strokeStyle = isSelected ? textColor : lineColor;
      ctx.stroke();

      const fontSize = Math.max(10 / globalScale, 3.2);
      ctx.font = `${fontSize}px Inter, sans-serif`;
      ctx.textAlign = "center";
      ctx.textBaseline = "top";
      ctx.fillStyle = textColor;
      ctx.fillText(node.label, node.x ?? 0, (node.y ?? 0) + radius + 2);
    },
    [colorForType, lineColor, selectedId, textColor],
  );

  const paintNodePointerArea = useCallback((node: RuntimeNode, color: string, ctx: CanvasRenderingContext2D) => {
    ctx.fillStyle = color;
    ctx.beginPath();
    ctx.arc(node.x ?? 0, node.y ?? 0, 9, 0, 2 * Math.PI);
    ctx.fill();
  }, []);

  const paintLinkLabel = useCallback((link: RuntimeLink, ctx: CanvasRenderingContext2D, globalScale: number) => {
    const source = link.source;
    const target = link.target;
    if (typeof source !== "object" || typeof target !== "object") return;
    const midX = ((source.x ?? 0) + (target.x ?? 0)) / 2;
    const midY = ((source.y ?? 0) + (target.y ?? 0)) / 2;
    const fontSize = Math.max(8 / globalScale, 2.8);
    ctx.font = `${fontSize}px "JetBrains Mono", monospace`;
    ctx.textAlign = "center";
    ctx.textBaseline = "middle";
    ctx.fillStyle = subduedTextColor;
    ctx.fillText(link.relationship, midX, midY);
  }, [subduedTextColor]);

  function handleFitView(): void {
    fgRef.current?.zoomToFit(400, 48);
  }

  function handleDownloadPng(): void {
    const canvas = containerRef.current?.querySelector("canvas");
    if (!canvas) return;
    const anchor = document.createElement("a");
    anchor.download = `${artifact.title.replace(/\s+/g, "_").toLowerCase()}.png`;
    anchor.href = (canvas as HTMLCanvasElement).toDataURL("image/png");
    anchor.click();
  }

  return (
    <div className="graph-artifact">
      <div className="graph-artifact-toolbar">
        <div className="graph-artifact-toolbar-title">
          <AssistantIcon name="graph" />
          <strong>{artifact.title}</strong>
        </div>
        <div className="graph-artifact-toolbar-actions">
          <button type="button" className="btn btn-ghost btn-sm" onClick={handleFitView}>
            <AssistantIcon name="fit" /> Fit view
          </button>
          <button type="button" className="btn btn-ghost btn-sm" onClick={handleDownloadPng}>
            <AssistantIcon name="download" /> PNG
          </button>
        </div>
      </div>

      <div className="graph-artifact-body">
        <div className="graph-artifact-canvas" ref={containerRef}>
          {size.width > 0 && size.height > 0 && (
            <ForceGraph2D
              ref={fgRef}
              graphData={graphData}
              width={size.width}
              height={size.height}
              backgroundColor={graphBackground}
              nodeRelSize={4}
              nodeCanvasObject={paintNode}
              nodePointerAreaPaint={paintNodePointerArea}
              linkColor={() => lineColor}
              linkWidth={1}
              linkCanvasObjectMode={() => "after"}
              linkCanvasObject={paintLinkLabel}
              linkDirectionalArrowLength={4}
              linkDirectionalArrowRelPos={1}
              cooldownTime={4000}
              onNodeClick={(node: RuntimeNode) =>
                setSelectedId((current) => (current === node.id ? null : node.id))
              }
              onBackgroundClick={() => setSelectedId(null)}
            />
          )}
        </div>

        <aside className="graph-results-overview">
          <h4>Results overview</h4>

          <div className="results-overview-group">
            <div className="results-overview-group-head">Nodes ({artifact.nodes.length})</div>
            <div className="results-overview-pills">
              <span className="overview-pill wildcard">* ({artifact.nodes.length})</span>
              {Array.from(nodeTypeCounts.entries()).map(([type, count]) => (
                <span
                  key={type}
                  className="overview-pill"
                  style={{ borderColor: colorForType.get(type), color: colorForType.get(type) }}
                >
                  {type} ({count})
                </span>
              ))}
            </div>
          </div>

          <div className="results-overview-group">
            <div className="results-overview-group-head">Relationships ({artifact.links.length})</div>
            <div className="results-overview-pills">
              <span className="overview-pill wildcard">* ({artifact.links.length})</span>
              {Array.from(relationshipCounts.entries()).map(([relationship, count]) => (
                <span key={relationship} className="overview-pill neutral">
                  {relationship} ({count})
                </span>
              ))}
            </div>
          </div>

          {selectedNode && (
            <div className="node-inspector">
              <div className="results-overview-group-head">Selected node</div>
              <strong>{selectedNode.label}</strong>
              <span
                className="node-inspector-type"
                style={{ color: colorForType.get(selectedNode.type) }}
              >
                {selectedNode.type}
              </span>
              {selectedNode.properties && Object.keys(selectedNode.properties).length > 0 && (
                <dl className="node-inspector-props">
                  {Object.entries(selectedNode.properties).map(([key, value]) => (
                    <div key={key}>
                      <dt>{key}</dt>
                      <dd>{value}</dd>
                    </div>
                  ))}
                </dl>
              )}
            </div>
          )}
        </aside>
      </div>

      {artifact.caption && <p className="graph-artifact-caption">{artifact.caption}</p>}
    </div>
  );
}
