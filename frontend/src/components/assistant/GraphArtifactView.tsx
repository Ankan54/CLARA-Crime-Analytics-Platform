import { useCallback, useEffect, useMemo, useState, type ReactNode } from "react";
import { createPortal } from "react-dom";
import {
  Background,
  BackgroundVariant,
  BaseEdge,
  EdgeLabelRenderer,
  Handle,
  MarkerType,
  Position,
  ReactFlow,
  ReactFlowProvider,
  getNodesBounds,
  useEdgesState,
  useNodesState,
  useReactFlow,
  type Edge,
  type EdgeProps,
  type Node,
  type NodeProps,
} from "@xyflow/react";
import "@xyflow/react/dist/style.css";
import type { GraphArtifact, GraphArtifactLink, GraphArtifactNode } from "../../lib/assistantTypes";
import { AssistantIcon } from "./icons";

// A dense hub renders as an unreadable ball; cap the drawn nodes at the highest-degree
// ones and tell the officer how many were hidden (Aura does the same on big graphs).
const MAX_VISIBLE_NODES = 60;
const NODE_W = 168;
const NODE_H = 52;
const LAYER_GAP_X = 240;
const LAYER_GAP_Y = 88;

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

type GraphNodeData = {
  label: string;
  type: string;
  color: string;
  dimmed: boolean;
};

type GraphEdgeData = {
  label: string;
  dimmed: boolean;
};

function GraphEntityNode({ data, selected }: NodeProps<Node<GraphNodeData>>) {
  return (
    <div
      className={`graph-flow-node${selected ? " is-selected" : ""}${data.dimmed ? " is-dimmed" : ""}`}
      style={{
        borderColor: data.color,
        background: `color-mix(in srgb, ${data.color} 18%, var(--surface))`,
        boxShadow: selected
          ? `0 0 0 2px color-mix(in srgb, ${data.color} 55%, transparent)`
          : undefined,
      }}
    >
      <Handle type="target" position={Position.Left} className="graph-flow-handle" />
      <span className="graph-flow-node-dot" style={{ background: data.color }} aria-hidden />
      <div className="graph-flow-node-body">
        <strong title={data.label}>{data.label}</strong>
        <span style={{ color: data.color }}>{data.type}</span>
      </div>
      <Handle type="source" position={Position.Right} className="graph-flow-handle" />
    </div>
  );
}

function GraphRelEdge({
  id,
  sourceX,
  sourceY,
  targetX,
  targetY,
  data,
  markerEnd,
  style,
}: EdgeProps<Edge<GraphEdgeData>>) {
  const midX = (sourceX + targetX) / 2;
  const midY = (sourceY + targetY) / 2;
  const edgePath = `M ${sourceX},${sourceY} L ${targetX},${targetY}`;
  const label = data?.label ?? "";
  const dimmed = Boolean(data?.dimmed);

  return (
    <>
      <BaseEdge
        id={id}
        path={edgePath}
        markerEnd={markerEnd}
        style={{
          ...style,
          opacity: dimmed ? 0.18 : 1,
          strokeWidth: dimmed ? 1 : (style?.strokeWidth as number | undefined) ?? 1.5,
        }}
      />
      {label && !dimmed && (
        <EdgeLabelRenderer>
          <div
            className="graph-flow-edge-label nodrag nopan"
            style={{
              transform: `translate(-50%, -50%) translate(${midX}px, ${midY}px)`,
            }}
          >
            {label}
          </div>
        </EdgeLabelRenderer>
      )}
    </>
  );
}

const nodeTypes = { graphEntity: GraphEntityNode };
const edgeTypes = { graphRel: GraphRelEdge };

/** Layered left→right layout from roots (prefer Victim / zero-indegree). Positions freeze after. */
function layoutPositions(
  nodes: GraphArtifactNode[],
  links: GraphArtifactLink[],
): Map<string, { x: number; y: number }> {
  const ids = new Set(nodes.map((n) => n.id));
  const indegree = new Map<string, number>();
  const outgoing = new Map<string, string[]>();
  nodes.forEach((n) => {
    indegree.set(n.id, 0);
    outgoing.set(n.id, []);
  });
  links.forEach((link) => {
    if (!ids.has(link.source) || !ids.has(link.target)) return;
    indegree.set(link.target, (indegree.get(link.target) ?? 0) + 1);
    outgoing.get(link.source)!.push(link.target);
  });

  const roots = nodes
    .filter((n) => (indegree.get(n.id) ?? 0) === 0)
    .sort((a, b) => {
      const score = (n: GraphArtifactNode) =>
        /victim/i.test(n.type) || /victim/i.test(n.label) ? 0 : 1;
      return score(a) - score(b) || a.label.localeCompare(b.label);
    });

  const layerOf = new Map<string, number>();
  const queue: string[] = [];
  const start = roots.length > 0 ? roots : nodes[0] ? [nodes[0]] : [];
  start.forEach((n) => {
    layerOf.set(n.id, 0);
    queue.push(n.id);
  });

  while (queue.length > 0) {
    const id = queue.shift()!;
    const layer = layerOf.get(id) ?? 0;
    for (const next of outgoing.get(id) ?? []) {
      const proposed = layer + 1;
      const existing = layerOf.get(next);
      if (existing == null || proposed > existing) {
        layerOf.set(next, proposed);
        queue.push(next);
      }
    }
  }

  let maxLayer = 0;
  layerOf.forEach((l) => {
    maxLayer = Math.max(maxLayer, l);
  });
  nodes.forEach((n) => {
    if (!layerOf.has(n.id)) {
      maxLayer += 1;
      layerOf.set(n.id, maxLayer);
    }
  });

  const byLayer = new Map<number, string[]>();
  layerOf.forEach((layer, id) => {
    if (!byLayer.has(layer)) byLayer.set(layer, []);
    byLayer.get(layer)!.push(id);
  });

  const labelOf = new Map(nodes.map((n) => [n.id, n.label]));
  byLayer.forEach((list) => {
    list.sort((a, b) => (labelOf.get(a) ?? "").localeCompare(labelOf.get(b) ?? ""));
  });

  const positions = new Map<string, { x: number; y: number }>();
  byLayer.forEach((list, layer) => {
    const totalH = (list.length - 1) * LAYER_GAP_Y;
    const startY = -totalH / 2;
    list.forEach((id, index) => {
      positions.set(id, {
        x: layer * LAYER_GAP_X,
        y: startY + index * LAYER_GAP_Y,
      });
    });
  });
  return positions;
}

function buildFlowNodes(
  nodes: GraphArtifactNode[],
  links: GraphArtifactLink[],
  colorForType: Map<string, string>,
): Node<GraphNodeData>[] {
  const positions = layoutPositions(nodes, links);
  return nodes.map((node) => {
    const pos = positions.get(node.id) ?? { x: 0, y: 0 };
    return {
      id: node.id,
      type: "graphEntity",
      position: pos,
      data: {
        label: node.label,
        type: node.type,
        color: colorForType.get(node.type) ?? "#60a5fa",
        dimmed: false,
      },
      draggable: true,
      selectable: true,
      style: { width: NODE_W, height: NODE_H },
    };
  });
}

function buildFlowEdges(links: GraphArtifactLink[], accent: string): Edge<GraphEdgeData>[] {
  return links.map((link, index) => ({
    id: `${link.source}->${link.target}:${link.relationship}:${index}`,
    source: link.source,
    target: link.target,
    type: "graphRel",
    data: { label: link.relationship, dimmed: false },
    selectable: true,
    markerEnd: {
      type: MarkerType.ArrowClosed,
      width: 14,
      height: 14,
      color: accent,
    },
    style: {
      stroke: "rgba(180, 200, 220, 0.55)",
      strokeWidth: 1.5,
    },
  }));
}

function FitOnMount({ nodeCount }: { nodeCount: number }) {
  const { fitView } = useReactFlow();
  useEffect(() => {
    if (nodeCount === 0) return;
    const timer = window.setTimeout(() => {
      void fitView({ padding: 0.18, duration: 280 });
    }, 40);
    return () => window.clearTimeout(timer);
  }, [fitView, nodeCount]);
  return null;
}

function ToolbarPortal({ artifactId, children }: { artifactId: string; children: ReactNode }) {
  const [slot, setSlot] = useState<HTMLElement | null>(null);
  useEffect(() => {
    setSlot(document.getElementById(`graph-flow-toolbar-slot-${artifactId}`));
  }, [artifactId]);
  if (!slot) return null;
  return createPortal(children, slot);
}

function GraphFlowInner({
  artifact,
  visibleNodes,
  visibleLinks,
  colorForType,
  selectedId,
  onSelect,
}: {
  artifact: GraphArtifact;
  visibleNodes: GraphArtifactNode[];
  visibleLinks: GraphArtifactLink[];
  colorForType: Map<string, string>;
  selectedId: string | null;
  onSelect: (id: string | null) => void;
}) {
  const accent = useMemo(() => readCssVar("--accent-strong", "#60a5fa"), []);
  const { fitView, getNodes } = useReactFlow();
  const [nodes, setNodes, onNodesChange] = useNodesState<Node<GraphNodeData>>([]);
  const [edges, setEdges, onEdgesChange] = useEdgesState<Edge<GraphEdgeData>>([]);
  const [hoveredId, setHoveredId] = useState<string | null>(null);

  const neighbours = useMemo(() => {
    const map = new Map<string, Set<string>>();
    const add = (a: string, b: string) => {
      if (!map.has(a)) map.set(a, new Set());
      map.get(a)!.add(b);
    };
    visibleLinks.forEach((link) => {
      add(link.source, link.target);
      add(link.target, link.source);
    });
    return map;
  }, [visibleLinks]);

  const focusId = hoveredId ?? selectedId;
  const focusSet = useMemo(() => {
    if (!focusId) return null;
    const set = new Set<string>([focusId]);
    neighbours.get(focusId)?.forEach((n) => set.add(n));
    return set;
  }, [focusId, neighbours]);

  const layoutKey = useMemo(
    () => `${artifact.id}:${visibleNodes.map((n) => n.id).join(",")}:${visibleLinks.length}`,
    [artifact.id, visibleNodes, visibleLinks],
  );

  // Seed layout only when topology changes — preserves drag positions otherwise.
  useEffect(() => {
    setNodes(buildFlowNodes(visibleNodes, visibleLinks, colorForType));
    setEdges(buildFlowEdges(visibleLinks, accent));
  }, [layoutKey, visibleNodes, visibleLinks, colorForType, accent, setNodes, setEdges]);

  // Patch dimming / selection without resetting positions.
  useEffect(() => {
    setNodes((nds) =>
      nds.map((node) => ({
        ...node,
        selected: node.id === selectedId,
        data: {
          ...node.data,
          dimmed: focusSet != null && !focusSet.has(node.id),
        },
      })),
    );
    setEdges((eds) =>
      eds.map((edge) => {
        const dimmed =
          focusSet != null && !(focusSet.has(edge.source) && focusSet.has(edge.target));
        return {
          ...edge,
          data: { ...(edge.data as GraphEdgeData), dimmed },
          markerEnd: {
            type: MarkerType.ArrowClosed,
            width: 14,
            height: 14,
            color: dimmed ? "rgba(255,255,255,0.12)" : accent,
          },
          style: {
            stroke: dimmed ? "rgba(255,255,255,0.08)" : "rgba(180, 200, 220, 0.55)",
            strokeWidth: 1.5,
          },
        };
      }),
    );
  }, [focusSet, selectedId, accent, setNodes, setEdges]);

  const onNodeClick = useCallback(
    (_event: React.MouseEvent, node: Node) => {
      onSelect(selectedId === node.id ? null : node.id);
    },
    [onSelect, selectedId],
  );

  function handleFitView(): void {
    void fitView({ padding: 0.18, duration: 280 });
  }

  function handleDownloadPng(): void {
    const current = getNodes();
    if (current.length === 0) return;
    const bounds = getNodesBounds(current);
    const pad = 48;
    const width = Math.max(320, Math.ceil(bounds.width + pad * 2));
    const height = Math.max(240, Math.ceil(bounds.height + pad * 2));
    const canvas = document.createElement("canvas");
    canvas.width = width;
    canvas.height = height;
    const ctx = canvas.getContext("2d");
    if (!ctx) return;

    const bg = readCssVar("--surface-inset", "#0d131c");
    const text = readCssVar("--text", "#f5f7fa");
    const mute = readCssVar("--text-dim", "#b6c0cc");
    ctx.fillStyle = bg;
    ctx.fillRect(0, 0, width, height);
    const ox = -bounds.x + pad;
    const oy = -bounds.y + pad;

    edges.forEach((edge) => {
      const source = current.find((n) => n.id === edge.source);
      const target = current.find((n) => n.id === edge.target);
      if (!source || !target) return;
      const x1 = source.position.x + NODE_W + ox;
      const y1 = source.position.y + NODE_H / 2 + oy;
      const x2 = target.position.x + ox;
      const y2 = target.position.y + NODE_H / 2 + oy;
      ctx.strokeStyle = "rgba(180, 200, 220, 0.55)";
      ctx.lineWidth = 1.5;
      ctx.beginPath();
      ctx.moveTo(x1, y1);
      ctx.lineTo(x2, y2);
      ctx.stroke();
      const label = (edge.data as GraphEdgeData | undefined)?.label;
      if (label) {
        ctx.fillStyle = mute;
        ctx.font = '10px "JetBrains Mono", monospace';
        ctx.textAlign = "center";
        ctx.fillText(label, (x1 + x2) / 2, (y1 + y2) / 2 - 4);
      }
    });

    current.forEach((node) => {
      const data = node.data as GraphNodeData;
      const x = node.position.x + ox;
      const y = node.position.y + oy;
      ctx.fillStyle = bg;
      ctx.strokeStyle = data.color;
      ctx.lineWidth = 2;
      ctx.beginPath();
      if (typeof ctx.roundRect === "function") {
        ctx.roundRect(x, y, NODE_W, NODE_H, 8);
      } else {
        ctx.rect(x, y, NODE_W, NODE_H);
      }
      ctx.fill();
      ctx.stroke();
      ctx.fillStyle = data.color;
      ctx.beginPath();
      ctx.arc(x + 14, y + NODE_H / 2, 5, 0, Math.PI * 2);
      ctx.fill();
      ctx.fillStyle = text;
      ctx.font = "600 12px Inter, sans-serif";
      ctx.textAlign = "left";
      const label = data.label.length > 22 ? `${data.label.slice(0, 21)}\u2026` : data.label;
      ctx.fillText(label, x + 26, y + 22);
      ctx.fillStyle = data.color;
      ctx.font = "10px Inter, sans-serif";
      ctx.fillText(data.type, x + 26, y + 38);
    });

    const anchor = document.createElement("a");
    anchor.download = `${artifact.title.replace(/\s+/g, "_").toLowerCase()}.png`;
    anchor.href = canvas.toDataURL("image/png");
    anchor.click();
  }

  return (
    <>
      <ToolbarPortal artifactId={artifact.id}>
        <button type="button" className="btn btn-ghost btn-sm" onClick={handleFitView}>
          <AssistantIcon name="fit" /> Fit view
        </button>
        <button type="button" className="btn btn-ghost btn-sm" onClick={handleDownloadPng}>
          <AssistantIcon name="download" /> PNG
        </button>
      </ToolbarPortal>

      <div className="graph-artifact-canvas">
        <ReactFlow
          nodes={nodes}
          edges={edges}
          onNodesChange={onNodesChange}
          onEdgesChange={onEdgesChange}
          onNodeClick={onNodeClick}
          onPaneClick={() => onSelect(null)}
          onNodeMouseEnter={(_e, node) => setHoveredId(node.id)}
          onNodeMouseLeave={() => setHoveredId(null)}
          nodeTypes={nodeTypes}
          edgeTypes={edgeTypes}
          fitView
          fitViewOptions={{ padding: 0.18 }}
          minZoom={0.25}
          maxZoom={1.8}
          proOptions={{ hideAttribution: true }}
          nodesDraggable
          nodesConnectable={false}
          elementsSelectable
          selectNodesOnDrag={false}
          panOnDrag
          panOnScroll
          selectionOnDrag={false}
          elevateEdgesOnSelect
          elevateNodesOnSelect
        >
          <Background
            variant={BackgroundVariant.Dots}
            gap={20}
            size={1.1}
            color="rgba(255, 255, 255, 0.07)"
          />
          <FitOnMount nodeCount={visibleNodes.length} />
        </ReactFlow>
      </div>
    </>
  );
}

/** Interactive React Flow graph with a Neo4j-style "Results overview" side panel. */
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

  const [selectedId, setSelectedId] = useState<string | null>(null);

  const degree = useMemo(() => {
    const map = new Map<string, number>();
    artifact.links.forEach((link) => {
      map.set(link.source, (map.get(link.source) ?? 0) + 1);
      map.set(link.target, (map.get(link.target) ?? 0) + 1);
    });
    return map;
  }, [artifact]);

  const { visibleNodes, visibleLinks, hiddenCount } = useMemo(() => {
    if (artifact.nodes.length <= MAX_VISIBLE_NODES) {
      return { visibleNodes: artifact.nodes, visibleLinks: artifact.links, hiddenCount: 0 };
    }
    const kept = [...artifact.nodes]
      .sort((a, b) => (degree.get(b.id) ?? 0) - (degree.get(a.id) ?? 0))
      .slice(0, MAX_VISIBLE_NODES);
    const keptIds = new Set(kept.map((n) => n.id));
    const links = artifact.links.filter((l) => keptIds.has(l.source) && keptIds.has(l.target));
    return { visibleNodes: kept, visibleLinks: links, hiddenCount: artifact.nodes.length - kept.length };
  }, [artifact, degree]);

  const nodeTypeCounts = useMemo(() => {
    const map = new Map<string, number>();
    visibleNodes.forEach((node) => map.set(node.type, (map.get(node.type) ?? 0) + 1));
    return map;
  }, [visibleNodes]);

  const relationshipCounts = useMemo(() => {
    const map = new Map<string, number>();
    visibleLinks.forEach((link) => map.set(link.relationship, (map.get(link.relationship) ?? 0) + 1));
    return map;
  }, [visibleLinks]);

  const colorForType = useMemo(() => {
    const types = Array.from(nodeTypeCounts.keys()).sort();
    const map = new Map<string, string>();
    types.forEach((type, index) => map.set(type, palette[index % palette.length]));
    return map;
  }, [nodeTypeCounts, palette]);

  const selectedNode = useMemo<GraphArtifactNode | null>(
    () => artifact.nodes.find((node) => node.id === selectedId) ?? null,
    [artifact, selectedId],
  );

  return (
    <div className="graph-artifact">
      <div className="graph-artifact-toolbar">
        <div className="graph-artifact-toolbar-title">
          <AssistantIcon name="graph" />
          <strong>{artifact.title}</strong>
        </div>
        <div id={`graph-flow-toolbar-slot-${artifact.id}`} className="graph-artifact-toolbar-actions" />
      </div>

      {hiddenCount > 0 && (
        <p className="graph-artifact-cap-note">
          Showing the {MAX_VISIBLE_NODES} most-connected of {artifact.nodes.length} nodes ({hiddenCount}{" "}
          hidden). Drag nodes to rearrange — positions stay put.
        </p>
      )}

      <div className="graph-artifact-body">
        <div className="graph-flow-host">
          <ReactFlowProvider>
            <GraphFlowInner
              artifact={artifact}
              visibleNodes={visibleNodes}
              visibleLinks={visibleLinks}
              colorForType={colorForType}
              selectedId={selectedId}
              onSelect={setSelectedId}
            />
          </ReactFlowProvider>
        </div>

        <aside className="graph-results-overview">
          <h4>Results overview</h4>

          <div className="results-overview-group">
            <div className="results-overview-group-head">Nodes ({visibleNodes.length})</div>
            <div className="results-overview-pills">
              <span className="overview-pill wildcard">* ({visibleNodes.length})</span>
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
            <div className="results-overview-group-head">Relationships ({visibleLinks.length})</div>
            <div className="results-overview-pills">
              <span className="overview-pill wildcard">* ({visibleLinks.length})</span>
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
