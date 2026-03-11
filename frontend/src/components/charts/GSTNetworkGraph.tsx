import { useEffect, useRef, useState, useMemo, useCallback } from 'react'
import {
  forceSimulation,
  forceLink,
  forceManyBody,
  forceCenter,
  forceCollide,
  type SimulationNodeDatum,
  type SimulationLinkDatum,
} from 'd3-force'
import { AlertTriangle, TrendingUp, TrendingDown, Activity, ZoomIn, ZoomOut, Maximize2 } from 'lucide-react'

/* ── Types ─────────────────────────────────────────────────────────── */

interface GraphNode {
  id: string
  name?: string
  total_sales: number
  total_purchases: number
  net_gst_paid: number
  risk_score: number
  is_circular: boolean
  is_suspicious: boolean
  sector?: string
  state?: string
}

interface GraphEdge {
  source: string
  target: string
  invoice_value: number
  tax_amount: number
  transaction_count: number
  is_circular: boolean
}

interface CircularPattern {
  cycle: string[]
  cycle_length: number
  cycle_value: number
  flag: string
  edges?: any[]
}

interface GSTNetworkGraphProps {
  nodes: GraphNode[]
  edges: GraphEdge[]
  circularPatterns?: CircularPattern[]
  height?: number
}

/* ── Internal simulation types ─────────────────────────────────────── */

interface SimNode extends SimulationNodeDatum {
  id: string
  name?: string
  total_sales: number
  total_purchases: number
  net_gst_paid: number
  risk_score: number
  is_circular: boolean
  is_suspicious: boolean
  sector?: string
  state?: string
  radius: number
  // d3-force mutates these in place
  x?: number
  y?: number
  fx?: number | null
  fy?: number | null
}

interface SimLink extends SimulationLinkDatum<SimNode> {
  sourceId: string
  targetId: string
  invoice_value: number
  tax_amount: number
  transaction_count: number
  is_circular: boolean
  thickness: number
  // d3-force resolves these from string → SimNode
  source: string | SimNode
  target: string | SimNode
}

/* ── Helpers ───────────────────────────────────────────────────────── */

function getNodeColor(node: { is_circular: boolean; is_suspicious: boolean; risk_score: number }) {
  if (node.is_circular) return '#EF4444'
  if (node.is_suspicious) return '#F97316'
  if (node.risk_score > 0.7) return '#DC2626'
  if (node.risk_score > 0.4) return '#F59E0B'
  return '#10B981'
}

function formatCurrency(value: number) {
  if (value >= 10000000) return `₹${(value / 10000000).toFixed(2)}Cr`
  if (value >= 100000) return `₹${(value / 100000).toFixed(2)}L`
  return `₹${value.toFixed(0)}`
}

/* ── Component ─────────────────────────────────────────────────────── */

export default function GSTNetworkGraph({
  nodes,
  edges,
  circularPatterns = [],
  height = 600,
}: GSTNetworkGraphProps) {
  const canvasRef = useRef<HTMLCanvasElement>(null)
  const containerRef = useRef<HTMLDivElement>(null)
  const simRef = useRef<ReturnType<typeof forceSimulation<SimNode>> | null>(null)
  const animRef = useRef<number>(0)

  const [containerWidth, setContainerWidth] = useState(800)
  const [hoverNode, setHoverNode] = useState<GraphNode | null>(null)
  const [selectedPattern, setSelectedPattern] = useState<number | null>(null)
  const [highlightNodes, setHighlightNodes] = useState<Set<string>>(new Set())
  const [highlightLinks, setHighlightLinks] = useState<Set<string>>(new Set())

  // Camera state (pan + zoom)
  const cameraRef = useRef({ x: 0, y: 0, scale: 1 })
  const dragRef = useRef<{
    dragging: boolean
    nodeId: string | null
    panStartX: number
    panStartY: number
    camStartX: number
    camStartY: number
  }>({ dragging: false, nodeId: null, panStartX: 0, panStartY: 0, camStartX: 0, camStartY: 0 })

  // Refs that the draw loop reads (avoids stale closures in rAF)
  const simNodesRef = useRef<SimNode[]>([])
  const simLinksRef = useRef<SimLink[]>([])
  const hlNodesRef = useRef<Set<string>>(new Set())
  const hlLinksRef = useRef<Set<string>>(new Set())
  hlNodesRef.current = highlightNodes
  hlLinksRef.current = highlightLinks

  // ── Resize observer ────────────────────────────────────────────────
  useEffect(() => {
    const el = containerRef.current
    if (!el) return
    const ro = new ResizeObserver(entries => {
      for (const entry of entries) setContainerWidth(entry.contentRect.width)
    })
    ro.observe(el)
    setContainerWidth(el.clientWidth || 800)
    return () => ro.disconnect()
  }, [])

  // ── Build sim data (memoised) ──────────────────────────────────────
  const { simNodes, simLinks } = useMemo(() => {
    const maxVal = Math.max(...nodes.map(n => Math.max(n.total_sales, n.total_purchases)), 1)
    const sn: SimNode[] = nodes.map(n => ({
      ...n,
      radius: 4 + 12 * Math.max(n.total_sales, n.total_purchases) / maxVal,
    }))
    const sl: SimLink[] = edges.map(e => ({
      source: e.source,
      target: e.target,
      sourceId: e.source,
      targetId: e.target,
      invoice_value: e.invoice_value,
      tax_amount: e.tax_amount,
      transaction_count: e.transaction_count,
      is_circular: e.is_circular,
      thickness: Math.max(e.invoice_value / (maxVal / 5), 0.5),
    }))
    return { simNodes: sn, simLinks: sl }
  }, [nodes, edges])

  // ── Highlight logic ────────────────────────────────────────────────
  useEffect(() => {
    if (selectedPattern !== null && circularPatterns[selectedPattern]) {
      const p = circularPatterns[selectedPattern]
      const nset = new Set(p.cycle)
      const lset = new Set<string>()
      for (let i = 0; i < p.cycle.length; i++) {
        lset.add(`${p.cycle[i]}-${p.cycle[(i + 1) % p.cycle.length]}`)
      }
      setHighlightNodes(nset)
      setHighlightLinks(lset)
    } else {
      setHighlightNodes(new Set())
      setHighlightLinks(new Set())
    }
  }, [selectedPattern, circularPatterns])

  // ── Render function (reads refs, no React state deps) ──────────────
  const draw = useCallback(() => {
    const canvas = canvasRef.current
    if (!canvas) return
    const ctx = canvas.getContext('2d')
    if (!ctx) return

    const dpr = window.devicePixelRatio || 1
    const w = containerWidth
    const h = height
    const cam = cameraRef.current
    const sNodes = simNodesRef.current
    const sLinks = simLinksRef.current
    const hlN = hlNodesRef.current
    const hlL = hlLinksRef.current

    // Ensure canvas buffer matches display size
    if (canvas.width !== w * dpr || canvas.height !== h * dpr) {
      canvas.width = w * dpr
      canvas.height = h * dpr
      canvas.style.width = `${w}px`
      canvas.style.height = `${h}px`
    }

    ctx.setTransform(dpr, 0, 0, dpr, 0, 0)
    ctx.clearRect(0, 0, w, h)
    ctx.fillStyle = '#0D1117'
    ctx.fillRect(0, 0, w, h)

    ctx.save()
    ctx.translate(w / 2 + cam.x, h / 2 + cam.y)
    ctx.scale(cam.scale, cam.scale)

    // ── Draw links ───────────────────────────────────────────────────
    for (const link of sLinks) {
      const src = link.source as unknown as SimNode
      const tgt = link.target as unknown as SimNode
      if (src.x == null || tgt.x == null || src.y == null || tgt.y == null) continue
      const linkId = `${link.sourceId}-${link.targetId}`
      const isHL = hlL.has(linkId)

      const dx = tgt.x - src.x
      const dy = tgt.y - src.y
      const dist = Math.sqrt(dx * dx + dy * dy)
      if (dist < 1) continue
      const endX = tgt.x - (dx / dist) * tgt.radius
      const endY = tgt.y - (dy / dist) * tgt.radius

      ctx.beginPath()
      ctx.moveTo(src.x, src.y)
      ctx.lineTo(endX, endY)
      ctx.strokeStyle = isHL
        ? (link.is_circular ? '#EF4444' : '#3B82F6')
        : (link.is_circular ? 'rgba(239,68,68,0.5)' : 'rgba(148,163,184,0.35)')
      ctx.lineWidth = isHL ? link.thickness * 2 : link.thickness
      ctx.stroke()

      // Arrowhead
      const al = 8 / cam.scale
      const angle = Math.atan2(dy, dx)
      ctx.beginPath()
      ctx.moveTo(endX, endY)
      ctx.lineTo(endX - al * Math.cos(angle - Math.PI / 7), endY - al * Math.sin(angle - Math.PI / 7))
      ctx.lineTo(endX - al * Math.cos(angle + Math.PI / 7), endY - al * Math.sin(angle + Math.PI / 7))
      ctx.closePath()
      ctx.fillStyle = ctx.strokeStyle
      ctx.fill()
    }

    // ── Draw nodes ───────────────────────────────────────────────────
    for (const node of sNodes) {
      if (node.x == null || node.y == null) continue
      const isHL = hlN.has(node.id)
      const r = isHL ? node.radius * 1.3 : node.radius

      // Glow for highlighted
      if (isHL) {
        ctx.beginPath()
        ctx.arc(node.x, node.y, r + 4, 0, Math.PI * 2)
        ctx.fillStyle = 'rgba(255,255,255,0.08)'
        ctx.fill()
      }

      // Node circle
      ctx.beginPath()
      ctx.arc(node.x, node.y, r, 0, Math.PI * 2)
      ctx.fillStyle = getNodeColor(node)
      ctx.fill()

      if (isHL) {
        ctx.strokeStyle = '#FFFFFF'
        ctx.lineWidth = 2 / cam.scale
        ctx.stroke()
      }

      // Circular marker dot
      if (node.is_circular) {
        const mr = r * 0.35
        ctx.beginPath()
        ctx.arc(node.x + r * 0.6, node.y - r * 0.6, mr, 0, Math.PI * 2)
        ctx.fillStyle = '#FCA5A5'
        ctx.fill()
        ctx.strokeStyle = '#EF4444'
        ctx.lineWidth = 1 / cam.scale
        ctx.stroke()
      }

      // Label
      if (cam.scale >= 1.2 || isHL) {
        const label = node.name || node.id.slice(0, 12)
        const fs = Math.max(10, 12 / cam.scale)
        ctx.font = `${fs}px Inter, system-ui, sans-serif`
        ctx.textAlign = 'center'
        ctx.textBaseline = 'top'
        ctx.fillStyle = '#E2E8F0'
        ctx.fillText(label, node.x, node.y + r + 3)
      }
    }

    ctx.restore()
  }, [containerWidth, height])

  // ── Force simulation setup ─────────────────────────────────────────
  useEffect(() => {
    // Deep-copy so d3 can mutate in place
    const nodesCopy: SimNode[] = simNodes.map(n => ({ ...n }))
    const linksCopy: SimLink[] = simLinks.map(l => ({ ...l }))
    simNodesRef.current = nodesCopy
    simLinksRef.current = linksCopy

    // Reset camera
    cameraRef.current = { x: 0, y: 0, scale: 1 }

    const sim = forceSimulation<SimNode>(nodesCopy)
      .force(
        'link',
        forceLink<SimNode, SimLink>(linksCopy)
          .id((d: SimNode) => d.id)
          .distance(100)
          .strength(0.4),
      )
      .force('charge', forceManyBody<SimNode>().strength(-200))
      .force('center', forceCenter(0, 0))
      .force('collide', forceCollide<SimNode>().radius((d: SimNode) => d.radius + 4))
      .alphaDecay(0.02)
      .velocityDecay(0.3)

    simRef.current = sim

    // Animation loop
    const tick = () => {
      draw()
      animRef.current = requestAnimationFrame(tick)
    }
    animRef.current = requestAnimationFrame(tick)

    return () => {
      cancelAnimationFrame(animRef.current)
      sim.stop()
    }
  }, [simNodes, simLinks, draw])

  // ── Mouse interaction helpers ──────────────────────────────────────
  const screenToWorld = useCallback(
    (sx: number, sy: number) => {
      const cam = cameraRef.current
      return {
        wx: (sx - containerWidth / 2 - cam.x) / cam.scale,
        wy: (sy - height / 2 - cam.y) / cam.scale,
      }
    },
    [containerWidth, height],
  )

  const findNodeAt = useCallback(
    (sx: number, sy: number): SimNode | null => {
      const { wx, wy } = screenToWorld(sx, sy)
      for (let i = simNodesRef.current.length - 1; i >= 0; i--) {
        const node = simNodesRef.current[i]
        if (node.x == null || node.y == null) continue
        const dx = node.x - wx
        const dy = node.y - wy
        if (dx * dx + dy * dy <= (node.radius + 4) ** 2) return node
      }
      return null
    },
    [screenToWorld],
  )

  const handleMouseDown = useCallback(
    (e: React.MouseEvent<HTMLCanvasElement>) => {
      const rect = canvasRef.current!.getBoundingClientRect()
      const sx = e.clientX - rect.left
      const sy = e.clientY - rect.top
      const node = findNodeAt(sx, sy)
      if (node) {
        dragRef.current = { dragging: true, nodeId: node.id, panStartX: sx, panStartY: sy, camStartX: 0, camStartY: 0 }
        node.fx = node.x
        node.fy = node.y
        simRef.current?.alphaTarget(0.3).restart()
      } else {
        dragRef.current = {
          dragging: true,
          nodeId: null,
          panStartX: sx,
          panStartY: sy,
          camStartX: cameraRef.current.x,
          camStartY: cameraRef.current.y,
        }
      }
    },
    [findNodeAt],
  )

  const handleMouseMove = useCallback(
    (e: React.MouseEvent<HTMLCanvasElement>) => {
      const rect = canvasRef.current!.getBoundingClientRect()
      const sx = e.clientX - rect.left
      const sy = e.clientY - rect.top
      const dr = dragRef.current

      if (dr.dragging && dr.nodeId) {
        const { wx, wy } = screenToWorld(sx, sy)
        const node = simNodesRef.current.find(n => n.id === dr.nodeId)
        if (node) {
          node.fx = wx
          node.fy = wy
        }
      } else if (dr.dragging) {
        cameraRef.current.x = dr.camStartX + (sx - dr.panStartX)
        cameraRef.current.y = dr.camStartY + (sy - dr.panStartY)
      } else {
        const node = findNodeAt(sx, sy)
        if (node) {
          setHoverNode(node as unknown as GraphNode)
          if (selectedPattern === null) {
            const cn = new Set([node.id])
            const cl = new Set<string>()
            edges.forEach(link => {
              if (link.source === node.id) {
                cn.add(link.target)
                cl.add(`${link.source}-${link.target}`)
              }
              if (link.target === node.id) {
                cn.add(link.source)
                cl.add(`${link.source}-${link.target}`)
              }
            })
            setHighlightNodes(cn)
            setHighlightLinks(cl)
          }
          if (canvasRef.current) canvasRef.current.style.cursor = 'pointer'
        } else {
          setHoverNode(null)
          if (selectedPattern === null) {
            setHighlightNodes(new Set())
            setHighlightLinks(new Set())
          }
          if (canvasRef.current) canvasRef.current.style.cursor = 'grab'
        }
      }
    },
    [findNodeAt, screenToWorld, edges, selectedPattern],
  )

  const handleMouseUp = useCallback(() => {
    const dr = dragRef.current
    if (dr.nodeId) {
      const node = simNodesRef.current.find(n => n.id === dr.nodeId)
      if (node) {
        node.fx = null
        node.fy = null
      }
      simRef.current?.alphaTarget(0)
    }
    dragRef.current = { dragging: false, nodeId: null, panStartX: 0, panStartY: 0, camStartX: 0, camStartY: 0 }
  }, [])

  const handleWheel = useCallback((e: React.WheelEvent<HTMLCanvasElement>) => {
    e.preventDefault()
    const factor = e.deltaY > 0 ? 0.9 : 1.1
    cameraRef.current.scale = Math.max(0.2, Math.min(5, cameraRef.current.scale * factor))
  }, [])

  const zoomIn = () => { cameraRef.current.scale = Math.min(5, cameraRef.current.scale * 1.3) }
  const zoomOut = () => { cameraRef.current.scale = Math.max(0.2, cameraRef.current.scale / 1.3) }
  const resetView = () => { cameraRef.current = { x: 0, y: 0, scale: 1 } }

  return (
    <div className="relative">
      {/* Header */}
      <div className="mb-4">
        <div className="flex items-center justify-between mb-2">
          <h3 className="text-lg font-semibold text-text-primary">GST Transaction Network</h3>
          <div className="flex items-center gap-2 text-xs text-text-secondary">
            <div className="flex items-center gap-1">
              <div className="w-3 h-3 rounded-full bg-red-500" />
              <span>Circular Trading</span>
            </div>
            <div className="flex items-center gap-1">
              <div className="w-3 h-3 rounded-full bg-orange-500" />
              <span>Suspicious</span>
            </div>
            <div className="flex items-center gap-1">
              <div className="w-3 h-3 rounded-full bg-green-500" />
              <span>Clean</span>
            </div>
          </div>
        </div>

        {/* Circular Pattern Selector */}
        {circularPatterns.length > 0 && (
          <div className="flex gap-2 overflow-x-auto pb-2">
            <button
              onClick={() => setSelectedPattern(null)}
              className={`px-3 py-1.5 rounded-lg text-sm font-medium transition-colors whitespace-nowrap ${
                selectedPattern === null
                  ? 'bg-primary text-white'
                  : 'bg-surface2 text-text-secondary hover:bg-surface-hover'
              }`}
            >
              Show All
            </button>
            {circularPatterns.map((pattern, idx) => (
              <button
                key={idx}
                onClick={() => setSelectedPattern(idx)}
                className={`px-3 py-1.5 rounded-lg text-sm font-medium transition-colors whitespace-nowrap flex items-center gap-1.5 ${
                  selectedPattern === idx
                    ? 'bg-red-500 text-white'
                    : 'bg-red-500/10 text-red-400 hover:bg-red-500/20'
                }`}
              >
                <AlertTriangle size={14} />
                Loop {idx + 1} ({pattern.cycle_length} nodes, {formatCurrency(pattern.cycle_value)})
              </button>
            ))}
          </div>
        )}
      </div>

      {/* Graph Canvas */}
      <div ref={containerRef} className="relative rounded-xl border border-border-dark bg-surface overflow-hidden" style={{ height }}>
        <canvas
          ref={canvasRef}
          onMouseDown={handleMouseDown}
          onMouseMove={handleMouseMove}
          onMouseUp={handleMouseUp}
          onMouseLeave={handleMouseUp}
          onWheel={handleWheel}
          className="block"
          style={{ cursor: 'grab', width: '100%', height: '100%' }}
        />

        {/* Zoom controls */}
        <div className="absolute top-3 right-3 flex flex-col gap-1 z-10">
          <button onClick={zoomIn} className="p-1.5 rounded-lg bg-surface2/80 backdrop-blur-sm border border-border-dark text-text-secondary hover:text-text-primary hover:bg-surface-hover transition-colors">
            <ZoomIn size={16} />
          </button>
          <button onClick={zoomOut} className="p-1.5 rounded-lg bg-surface2/80 backdrop-blur-sm border border-border-dark text-text-secondary hover:text-text-primary hover:bg-surface-hover transition-colors">
            <ZoomOut size={16} />
          </button>
          <button onClick={resetView} className="p-1.5 rounded-lg bg-surface2/80 backdrop-blur-sm border border-border-dark text-text-secondary hover:text-text-primary hover:bg-surface-hover transition-colors">
            <Maximize2 size={16} />
          </button>
        </div>

        {/* Hover Tooltip */}
        {hoverNode && (
          <div className="absolute top-4 left-4 bg-surface rounded-lg shadow-xl p-4 max-w-xs border border-border-dark z-10">
            <div className="flex items-start justify-between mb-2">
              <div>
                <div className="text-xs font-medium text-text-muted mb-0.5">GSTIN</div>
                <div className="text-sm font-mono font-semibold text-text-primary">{hoverNode.id}</div>
              </div>
              <div
                className={`px-2 py-0.5 rounded text-xs font-medium ${
                  hoverNode.is_circular
                    ? 'bg-red-500/20 text-red-400'
                    : hoverNode.is_suspicious
                      ? 'bg-orange-500/20 text-orange-400'
                      : 'bg-green-500/20 text-green-400'
                }`}
              >
                {hoverNode.is_circular ? 'Circular' : hoverNode.is_suspicious ? 'Suspicious' : 'Clean'}
              </div>
            </div>

            <div className="space-y-2 text-xs">
              <div className="flex items-center justify-between pb-2 border-b border-border-dark">
                <span className="text-text-secondary flex items-center gap-1">
                  <TrendingUp size={12} className="text-emerald-600" />
                  Sales
                </span>
                <span className="font-semibold text-text-primary">{formatCurrency(hoverNode.total_sales)}</span>
              </div>
              <div className="flex items-center justify-between pb-2 border-b border-border-dark">
                <span className="text-text-secondary flex items-center gap-1">
                  <TrendingDown size={12} className="text-blue-600" />
                  Purchases
                </span>
                <span className="font-semibold text-text-primary">{formatCurrency(hoverNode.total_purchases)}</span>
              </div>
              <div className="flex items-center justify-between pb-2 border-b border-border-dark">
                <span className="text-text-secondary flex items-center gap-1">
                  <Activity size={12} className="text-purple-600" />
                  Net GST
                </span>
                <span className="font-semibold text-text-primary">{formatCurrency(hoverNode.net_gst_paid)}</span>
              </div>
              <div className="flex items-center justify-between pt-1">
                <span className="text-text-secondary">Risk Score</span>
                <div className="flex items-center gap-2">
                  <div className="w-16 h-1.5 bg-border-dark rounded-full overflow-hidden">
                    <div
                      className={`h-full ${
                        hoverNode.risk_score > 0.7
                          ? 'bg-red-500'
                          : hoverNode.risk_score > 0.4
                            ? 'bg-orange-500'
                            : 'bg-green-500'
                      }`}
                      style={{ width: `${hoverNode.risk_score * 100}%` }}
                    />
                  </div>
                  <span className="font-semibold text-text-primary w-8 text-right">
                    {(hoverNode.risk_score * 10).toFixed(1)}
                  </span>
                </div>
              </div>
            </div>

            {hoverNode.sector && (
              <div className="mt-2 pt-2 border-t border-border-dark text-xs text-text-secondary">
                <span className="font-medium">Sector:</span> {hoverNode.sector}
              </div>
            )}
          </div>
        )}

        {/* Stats Overlay */}
        <div className="absolute bottom-4 right-4 bg-surface/90 backdrop-blur-sm rounded-lg shadow-lg p-3 text-xs">
          <div className="grid grid-cols-2 gap-x-4 gap-y-1.5">
            <div className="text-text-secondary">Nodes:</div>
            <div className="font-semibold text-text-primary">{nodes.length}</div>
            <div className="text-text-secondary">Transactions:</div>
            <div className="font-semibold text-text-primary">{edges.length}</div>
            <div className="text-text-secondary">Circular Loops:</div>
            <div className="font-semibold text-red-400">{circularPatterns.length}</div>
          </div>
        </div>
      </div>
    </div>
  )
}
