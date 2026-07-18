import { useCallback, useEffect, useMemo, useRef } from "react";
import {
  Background,
  BackgroundVariant,
  Controls,
  MarkerType,
  MiniMap,
  ReactFlow,
  ReactFlowProvider,
  BaseEdge,
  EdgeLabelRenderer,
  Handle,
  Position,
  useEdgesState,
  useNodesState,
  useReactFlow,
  type Edge,
  type EdgeProps,
  type Node,
  type NodeProps,
} from "@xyflow/react";
import "@xyflow/react/dist/style.css";
import type { OntologyEntity, OntologyRelationship } from "../../lib/api";

const NODE_SIZE = 128;
const PALETTE = [
  "#5b8def",
  "#3db8a8",
  "#e08a3c",
  "#e0719a",
  "#9b7de8",
  "#35c9d6",
  "#9fd67a",
  "#c99457",
];

function colorForId(id: string): string {
  let hash = 0;
  for (let i = 0; i < id.length; i += 1) {
    hash = (hash * 31 + id.charCodeAt(i)) | 0;
  }
  return PALETTE[Math.abs(hash) % PALETTE.length];
}

type OntologyNodeData = {
  label: string;
  keyProperty?: string | null;
  color: string;
};

type OntologyEdgeData = {
  label: string;
  offsetX?: number;
  offsetY?: number;
};

function OntologyEntityNode({ data, selected }: NodeProps<Node<OntologyNodeData>>) {
  const color = data.color;
  return (
    <div
      className={`ontology-node${selected ? " is-selected" : ""}`}
      style={{
        borderColor: color,
        background: `${color}22`,
        boxShadow: selected
          ? `0 0 0 3px rgba(255,255,255,0.55), 0 0 0 1px ${color}55 inset`
          : `0 0 0 1px ${color}55 inset`,
      }}
    >
      <Handle type="target" position={Position.Top} className="ontology-handle" />
      <Handle type="target" position={Position.Left} className="ontology-handle" />
      <strong className="ontology-node-label">{data.label}</strong>
      {data.keyProperty ? (
        <span className="ontology-node-key">
          <span className="ontology-node-key-mark" style={{ color }} aria-hidden>
            ♦
          </span>
          {data.keyProperty}
        </span>
      ) : null}
      <span className="ontology-node-dot" style={{ background: color }} aria-hidden />
      <Handle type="source" position={Position.Bottom} className="ontology-handle" />
      <Handle type="source" position={Position.Right} className="ontology-handle" />
    </div>
  );
}

function OntologyRelEdge({
  id,
  sourceX,
  sourceY,
  targetX,
  targetY,
  data,
  markerEnd,
  style,
  selected,
}: EdgeProps<Edge<OntologyEdgeData>>) {
  const { setEdges, screenToFlowPosition } = useReactFlow();
  const dragging = useRef(false);

  const offsetX = data?.offsetX ?? 0;
  const offsetY = data?.offsetY ?? 0;
  const controlX = (sourceX + targetX) / 2 + offsetX;
  const controlY = (sourceY + targetY) / 2 + offsetY;
  const edgePath = `M ${sourceX},${sourceY} Q ${controlX},${controlY} ${targetX},${targetY}`;
  const label = data?.label ?? "";

  const selectThisEdge = useCallback(() => {
    setEdges((eds) =>
      eds.map((edge) => ({
        ...edge,
        selected: edge.id === id,
      })),
    );
  }, [id, setEdges]);

  const onLabelPointerDown = useCallback(
    (event: React.PointerEvent<HTMLDivElement>) => {
      event.preventDefault();
      event.stopPropagation();
      dragging.current = true;
      selectThisEdge();
      event.currentTarget.setPointerCapture(event.pointerId);

      const onMove = (moveEvent: PointerEvent) => {
        if (!dragging.current) return;
        const pos = screenToFlowPosition({ x: moveEvent.clientX, y: moveEvent.clientY });
        const baseX = (sourceX + targetX) / 2;
        const baseY = (sourceY + targetY) / 2;
        setEdges((eds) =>
          eds.map((edge) =>
            edge.id === id
              ? {
                  ...edge,
                  selected: true,
                  data: {
                    ...(edge.data as OntologyEdgeData),
                    offsetX: pos.x - baseX,
                    offsetY: pos.y - baseY,
                  },
                }
              : { ...edge, selected: false },
          ),
        );
      };

      const onUp = (upEvent: PointerEvent) => {
        dragging.current = false;
        window.removeEventListener("pointermove", onMove);
        window.removeEventListener("pointerup", onUp);
        try {
          (upEvent.target as HTMLElement | null)?.releasePointerCapture?.(upEvent.pointerId);
        } catch {
          /* already released */
        }
      };

      window.addEventListener("pointermove", onMove);
      window.addEventListener("pointerup", onUp);
    },
    [id, screenToFlowPosition, selectThisEdge, setEdges, sourceX, sourceY, targetX, targetY],
  );

  return (
    <>
      <BaseEdge
        id={id}
        path={edgePath}
        markerEnd={markerEnd}
        style={{
          ...style,
          stroke: selected ? "var(--accent-strong)" : style?.stroke,
          strokeWidth: selected ? 2.5 : (style?.strokeWidth as number | undefined) ?? 1.5,
        }}
        interactionWidth={28}
      />
      <EdgeLabelRenderer>
        <div
          className={`ontology-edge-label nodrag nopan${selected ? " is-selected" : ""}`}
          style={{
            transform: `translate(-50%, -50%) translate(${controlX}px, ${controlY}px)`,
          }}
          onPointerDown={onLabelPointerDown}
          onClick={(event) => {
            event.stopPropagation();
            selectThisEdge();
          }}
          title="Drag to bend relationship"
        >
          {label}
        </div>
      </EdgeLabelRenderer>
    </>
  );
}

const nodeTypes = { ontology: OntologyEntityNode };
const edgeTypes = { ontology: OntologyRelEdge };

function circularLayout(entities: OntologyEntity[]): Node<OntologyNodeData>[] {
  const n = entities.length;
  const radius = Math.max(220, n * 42);
  const cx = 420;
  const cy = 320;
  return entities.map((entity, index) => {
    const angle = n === 1 ? -Math.PI / 2 : (2 * Math.PI * index) / n - Math.PI / 2;
    const color = colorForId(entity.id);
    return {
      id: entity.id,
      type: "ontology",
      position: {
        x: cx + radius * Math.cos(angle) - NODE_SIZE / 2,
        y: cy + radius * Math.sin(angle) - NODE_SIZE / 2,
      },
      data: {
        label: entity.label,
        keyProperty: entity.keyProperty,
        color,
      },
      style: { width: NODE_SIZE, height: NODE_SIZE },
      draggable: true,
      selectable: true,
      focusable: true,
    };
  });
}

function buildEdges(relationships: OntologyRelationship[]): Edge<OntologyEdgeData>[] {
  return relationships.map((rel) => ({
    id: rel.id,
    source: rel.from,
    target: rel.to,
    type: "ontology",
    data: { label: rel.type, offsetX: 0, offsetY: 0 },
    selectable: true,
    focusable: true,
    interactionWidth: 28,
    markerEnd: {
      type: MarkerType.ArrowClosed,
      width: 16,
      height: 16,
      color: "rgba(200, 210, 225, 0.7)",
    },
    style: { stroke: "rgba(200, 210, 225, 0.45)", strokeWidth: 1.5 },
  }));
}

function OntologyFlowCanvas({
  entities,
  relationships,
}: {
  entities: OntologyEntity[];
  relationships: OntologyRelationship[];
}) {
  const initialNodes = useMemo(() => circularLayout(entities), [entities]);
  const initialEdges = useMemo(() => buildEdges(relationships), [relationships]);
  const [nodes, setNodes, onNodesChange] = useNodesState(initialNodes);
  const [edges, setEdges, onEdgesChange] = useEdgesState(initialEdges);

  useEffect(() => {
    setNodes(circularLayout(entities));
  }, [entities, setNodes]);

  useEffect(() => {
    setEdges(buildEdges(relationships));
  }, [relationships, setEdges]);

  const onNodeClick = useCallback(
    (_event: React.MouseEvent, node: Node) => {
      setNodes((nds) => nds.map((n) => ({ ...n, selected: n.id === node.id })));
      setEdges((eds) => eds.map((e) => ({ ...e, selected: false })));
    },
    [setEdges, setNodes],
  );

  const onEdgeClick = useCallback(
    (_event: React.MouseEvent, edge: Edge) => {
      setEdges((eds) => eds.map((e) => ({ ...e, selected: e.id === edge.id })));
      setNodes((nds) => nds.map((n) => ({ ...n, selected: false })));
    },
    [setEdges, setNodes],
  );

  const onPaneClick = useCallback(() => {
    setNodes((nds) => nds.map((n) => ({ ...n, selected: false })));
    setEdges((eds) => eds.map((e) => ({ ...e, selected: false })));
  }, [setEdges, setNodes]);

  const nodeColor = (node: Node) =>
    (node.data as OntologyNodeData | undefined)?.color ?? "#5b8def";

  return (
    <ReactFlow
      nodes={nodes}
      edges={edges}
      onNodesChange={onNodesChange}
      onEdgesChange={onEdgesChange}
      onNodeClick={onNodeClick}
      onEdgeClick={onEdgeClick}
      onPaneClick={onPaneClick}
      nodeTypes={nodeTypes}
      edgeTypes={edgeTypes}
      fitView
      fitViewOptions={{ padding: 0.18 }}
      minZoom={0.35}
      maxZoom={1.8}
      proOptions={{ hideAttribution: true }}
      nodesDraggable
      nodesConnectable={false}
      nodesFocusable
      edgesFocusable
      elementsSelectable
      selectNodesOnDrag={false}
      panOnDrag
      panOnScroll
      selectionOnDrag={false}
      elevateEdgesOnSelect
      elevateNodesOnSelect
    >
      <Background
        id="ontology-dots"
        variant={BackgroundVariant.Dots}
        gap={22}
        size={1.2}
        color="rgba(255, 255, 255, 0.08)"
      />
      <Controls showInteractive={false} className="ontology-controls" />
      <MiniMap
        className="ontology-minimap"
        nodeColor={nodeColor}
        maskColor="rgba(7, 10, 16, 0.72)"
        pannable
        zoomable
      />
    </ReactFlow>
  );
}

export function OntologyGraph({
  entities,
  relationships,
}: {
  entities: OntologyEntity[];
  relationships: OntologyRelationship[];
}) {
  return (
    <div className="ontology-canvas">
      <ReactFlowProvider>
        <OntologyFlowCanvas entities={entities} relationships={relationships} />
      </ReactFlowProvider>
    </div>
  );
}
