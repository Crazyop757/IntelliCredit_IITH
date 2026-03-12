import React from 'react'
import { useNavigate } from 'react-router-dom'
import { useAuthStore } from '../store/authStore'
import { supabase } from '../lib/supabase'

const STYLES = `
@import url('https://fonts.googleapis.com/css2?family=Inter:wght@300;800&display=swap');

:root {
  --bg: #080C14;
  --blue: #2563EB;
  --green: #00FF94;
  --red: #FF3B30;
  --amber: #FFAA00;
  --slate-400: #94A3B8;
  --slate-500: #64748B;
  --slate-700: #334155;
  --border: #1E293B;
  --card: #0D1117;
  --deep: #050810;
}

* { margin: 0; padding: 0; box-sizing: border-box; }

.lp {
  font-family: 'Inter', system-ui, sans-serif;
  background: var(--bg);
  color: #fff;
  overflow-x: hidden;
  -webkit-font-smoothing: antialiased;
}

/* ── NOISE TEXTURE ────────────────────────────────────────────── */
.noise::before {
  content: '';
  position: fixed;
  inset: 0;
  z-index: 0;
  opacity: 0.035;
  pointer-events: none;
  background: url("data:image/svg+xml,%3Csvg xmlns='http://www.w3.org/2000/svg' width='200' height='200'%3E%3Cfilter id='n'%3E%3CfeTurbulence type='fractalNoise' baseFrequency='0.85' numOctaves='4' stitchTiles='stitch'/%3E%3C/filter%3E%3Crect width='100%25' height='100%25' filter='url(%23n)'/%3E%3C/svg%3E");
}

/* ── TICKER ───────────────────────────────────────────────────── */
@keyframes tickerScroll {
  0% { transform: translateY(0); }
  100% { transform: translateY(-50%); }
}
.ticker-track {
  animation: tickerScroll 18s linear infinite;
}
.ticker-track:hover { animation-play-state: paused; }

/* ── 3D GRAPH ─────────────────────────────────────────────────── */
@keyframes graphRotate {
  from { transform: rotateX(-8deg) rotateY(0deg); }
  to   { transform: rotateX(-8deg) rotateY(360deg); }
}
@keyframes nodeFloat {
  0%, 100% { transform: translateY(0px) translateZ(0); }
  50%      { transform: translateY(-8px) translateZ(4px); }
}
@keyframes pulseGlow {
  0%, 100% { opacity: 0.6; }
  50%      { opacity: 1; }
}
.graph-scene {
  transform-style: preserve-3d;
  animation: graphRotate 24s linear infinite;
}
.graph-node {
  animation: nodeFloat 3s ease-in-out infinite;
}
.fraud-edge {
  animation: pulseGlow 2s ease-in-out infinite;
}

/* ── PERSPECTIVE GRID ─────────────────────────────────────────── */
.grid-floor {
  position: absolute;
  bottom: -60px;
  left: 50%;
  translate: -50% 0;
  width: 600px;
  height: 200px;
  background:
    linear-gradient(90deg, rgba(37,99,235,0.07) 1px, transparent 1px),
    linear-gradient(0deg, rgba(37,99,235,0.07) 1px, transparent 1px);
  background-size: 40px 40px;
  transform: perspective(400px) rotateX(60deg);
  mask-image: linear-gradient(to top, rgba(0,0,0,0.4), transparent);
  -webkit-mask-image: linear-gradient(to top, rgba(0,0,0,0.4), transparent);
}

/* ── MARCHING ANTS ────────────────────────────────────────────── */
@keyframes march {
  to { stroke-dashoffset: -20; }
}
.marching-line {
  stroke-dasharray: 6 4;
  animation: march 0.8s linear infinite;
}

/* ── TERMINAL TYPING ──────────────────────────────────────────── */
@keyframes fadeInLine {
  from { opacity: 0; transform: translateY(4px); }
  to   { opacity: 1; transform: translateY(0); }
}
@keyframes blink {
  0%, 100% { opacity: 1; }
  50% { opacity: 0; }
}
.term-line {
  opacity: 0;
  animation: fadeInLine 0.3s ease forwards;
}
.term-cursor {
  display: inline-block;
  width: 7px;
  height: 14px;
  background: var(--green);
  animation: blink 1s step-end infinite;
  vertical-align: middle;
  margin-left: 2px;
}

/* ── CARD BOTTOM BAR ──────────────────────────────────────────── */
.card-bar {
  position: absolute;
  bottom: 0;
  left: 0;
  height: 2px;
  width: 0;
  transition: width 0.35s ease;
}
.feature-card:hover .card-bar {
  width: 100%;
}
.feature-card {
  transition: border-color 0.2s ease;
}
.feature-card:hover {
  border-color: var(--blue) !important;
}

/* ── STAT HOVER ───────────────────────────────────────────────── */
.stat-col {
  transition: background 0.2s ease;
}
.stat-col:hover {
  background: #0F172A;
}
.stat-col:hover .stat-num {
  color: var(--green);
}

/* ── RESPONSIVE ───────────────────────────────────────────────── */
@media (max-width: 768px) {
  .hero-grid { flex-direction: column !important; }
  .hero-text { text-align: center; align-items: center; }
  .hero-title { font-size: 48px !important; }
  .features-grid { grid-template-columns: 1fr !important; }
  .pipeline-row { flex-direction: column !important; align-items: center !important; }
  .pipeline-connector { display: none !important; }
  .ews-split { flex-direction: column !important; }
  .ticker-panel { display: none !important; }
}
`

/* ═══════════════════════════════════════════════════════════════════
   DATA
   ═══════════════════════════════════════════════════════════════════ */

const GRAPH_NODES: { id: string; x: number; y: number; z: number; fraud: boolean }[] = [
  { id: '08AA', x: 0, y: 0, z: 0, fraud: true },
  { id: '27MA', x: 120, y: -40, z: 30, fraud: true },
  { id: '07DL', x: 60, y: 80, z: -20, fraud: true },
  { id: '29KA', x: -100, y: -60, z: 40, fraud: false },
  { id: '33TN', x: -80, y: 60, z: -30, fraud: false },
  { id: '06HR', x: 160, y: 40, z: -10, fraud: false },
  { id: '09UP', x: -140, y: 10, z: 20, fraud: false },
  { id: '24GJ', x: 40, y: -100, z: -40, fraud: false },
  { id: '20JH', x: -50, y: -90, z: 50, fraud: false },
  { id: '32KL', x: 100, y: 90, z: 10, fraud: false },
  { id: '19WB', x: -160, y: -30, z: -20, fraud: false },
  { id: '03PB', x: 140, y: -80, z: -30, fraud: false },
]

const GRAPH_EDGES: { from: string; to: string; fraud: boolean }[] = [
  { from: '08AA', to: '27MA', fraud: true },
  { from: '27MA', to: '07DL', fraud: true },
  { from: '07DL', to: '08AA', fraud: true },
  { from: '29KA', to: '08AA', fraud: false },
  { from: '33TN', to: '07DL', fraud: false },
  { from: '06HR', to: '27MA', fraud: false },
  { from: '09UP', to: '29KA', fraud: false },
  { from: '24GJ', to: '27MA', fraud: false },
  { from: '20JH', to: '09UP', fraud: false },
  { from: '32KL', to: '06HR', fraud: false },
  { from: '19WB', to: '33TN', fraud: false },
  { from: '03PB', to: '24GJ', fraud: false },
  { from: '33TN', to: '29KA', fraud: false },
  { from: '06HR', to: '32KL', fraud: false },
]

const TICKER_LINES = [
  '\u2B24 CIRCULAR TRADE DETECTED \u2014 GSTIN 08XXFIC \u2014 \u20B942.8L',
  '\u2B24 ITC OVERCLAIM \u2014 GSTR-3B GAP 18.4% \u2014 HIGH RISK',
  '\u2B24 WILFUL DEFAULT FLAG \u2014 DIRECTOR MATCH',
  '\u2B24 DSCR BELOW THRESHOLD \u2014 0.94x',
  '\u2B24 ECS BOUNCE \u00D7 3 \u2014 CASH STRESS',
  '\u2B24 REVENUE-GST MISMATCH \u2014 \u20B91.2Cr DELTA',
  '\u2B24 PROMOTER PLEDGE 68% \u2014 ELEVATED RISK',
  '\u2B24 SMA-2 CLASSIFICATION \u2014 NPA WATCH',
]

const FEATURES = [
  {
    key: 'CHARACTER',
    metric: 'Director Intel',
    desc: 'RBI defaulter matching, eCourts litigation scan, promoter network analysis.',
    color: '#2563EB',
    icon: 'hexagon',
  },
  {
    key: 'CAPACITY',
    metric: '35 Features',
    desc: 'Revenue trends, DSCR, EBITDA margin, cash flow extraction from unstructured PDFs.',
    color: '#00FF94',
    icon: 'bars',
  },
  {
    key: 'CAPITAL',
    metric: 'Balance Sheet AI',
    desc: 'Net worth, D/E ratio, reserves & surplus parsed from annual reports via BERT-NER.',
    color: '#FFAA00',
    icon: 'diamond',
  },
  {
    key: 'COLLATERAL',
    metric: 'MCA Charges',
    desc: 'Charge search, security coverage analysis, valuation cross-reference.',
    color: '#A855F7',
    icon: 'shield',
  },
  {
    key: 'CONDITIONS',
    metric: 'Market Signals',
    desc: 'Sector NPA rates, macro risk via Tavily news intelligence, regulatory compliance.',
    color: '#06B6D4',
    icon: 'globe',
  },
  {
    key: 'AI MODELS',
    metric: 'GraphSAGE + FinBERT',
    desc: 'GNN fraud detection, NLP sentiment scoring, LightGBM+RF ensemble with SHAP.',
    color: '#FF3B30',
    icon: 'neural',
  },
]

const PIPELINE = [
  { n: 1, name: 'INGEST', desc: 'PDF + OCR + NER', active: false },
  { n: 2, name: 'ANALYSE', desc: 'Bank + GST recon', active: false },
  { n: 3, name: 'DETECT', desc: 'GNN fraud graph', active: true },
  { n: 4, name: 'RESEARCH', desc: 'LangGraph agent', active: false },
  { n: 5, name: 'SCORE', desc: 'Ensemble + SHAP', active: false },
]

const TERM_LINES = [
  '> Loading EWS Engine v2.4.1...',
  '> Ingesting GSTR-3B: aravali_FY2024.json',
  '> ITC Gap detected: 18.4% [SUSPICIOUS]',
  '> Circular trade nodes: 08AABCE7788, 08AABCF9900',
  '> Running GraphSAGE inference...',
  '> Fraud probability: 0.73 [HIGH_RISK]',
  '> DSCR: 1.45x \u2014 within threshold',
  '> ECS bounces: 2 \u2014 [MODERATE]',
  '> Auditor flag: EMPHASIS OF MATTER detected',
  '> EWS composite score: 2.84 / 5.00',
  '> SMA Classification: SMA-1',
  '> CAM generation initiated...',
]

const EWS_BULLETS = [
  { text: 'ITC Overclaim Detection via GSTR-2A vs 3B reconciliation', color: '#FF3B30' },
  { text: 'Circular Trading via GraphSAGE transaction graph analysis', color: '#FFAA00' },
  { text: 'Revenue Inflation via GST-to-bank credit mismatch', color: '#EAB308' },
  { text: 'Director Risk via RBI defaulter + eCourts cross-reference', color: '#2563EB' },
]

/* ═══════════════════════════════════════════════════════════════════
   SVG ICONS (pure inline)
   ═══════════════════════════════════════════════════════════════════ */

function CardIcon({ type, color }: { type: string; color: string }) {
  const s: React.CSSProperties = { width: 28, height: 28 }
  switch (type) {
    case 'hexagon':
      return (
        <svg viewBox="0 0 28 28" style={s} fill="none" stroke={color} strokeWidth="1.5">
          <polygon points="14,2 25,8 25,20 14,26 3,20 3,8" />
        </svg>
      )
    case 'bars':
      return (
        <svg viewBox="0 0 28 28" style={s} fill={color}>
          <rect x="4" y="16" width="5" height="10" rx="1" />
          <rect x="11.5" y="8" width="5" height="18" rx="1" />
          <rect x="19" y="12" width="5" height="14" rx="1" />
        </svg>
      )
    case 'diamond':
      return (
        <svg viewBox="0 0 28 28" style={s} fill="none" stroke={color} strokeWidth="1.5">
          <polygon points="14,2 26,14 14,26 2,14" />
        </svg>
      )
    case 'shield':
      return (
        <svg viewBox="0 0 28 28" style={s} fill="none" stroke={color} strokeWidth="1.5">
          <path d="M14 3 L24 7 L24 15 C24 20 19 24 14 26 C9 24 4 20 4 15 L4 7 Z" />
        </svg>
      )
    case 'globe':
      return (
        <svg viewBox="0 0 28 28" style={s} fill="none" stroke={color} strokeWidth="1.5">
          <circle cx="14" cy="14" r="11" />
          <ellipse cx="14" cy="14" rx="5" ry="11" />
          <line x1="3" y1="10" x2="25" y2="10" />
          <line x1="3" y1="18" x2="25" y2="18" />
        </svg>
      )
    case 'neural':
      return (
        <svg viewBox="0 0 28 28" style={s} fill="none" stroke={color} strokeWidth="1.2">
          <circle cx="6" cy="8" r="3" />
          <circle cx="6" cy="20" r="3" />
          <circle cx="22" cy="14" r="3" />
          <line x1="9" y1="8" x2="19" y2="14" />
          <line x1="9" y1="20" x2="19" y2="14" />
          <line x1="6" y1="11" x2="6" y2="17" />
        </svg>
      )
    default:
      return null
  }
}

/* ═══════════════════════════════════════════════════════════════════
   3D GRAPH COMPONENT
   ═══════════════════════════════════════════════════════════════════ */

function FraudGraph() {
  const nodeMap = Object.fromEntries(GRAPH_NODES.map((n) => [n.id, n]))

  return (
    <div style={{ perspective: '800px', width: 420, height: 340, position: 'relative' }}>
      {/* Radial glow */}
      <div
        style={{
          position: 'absolute',
          inset: 0,
          background: 'radial-gradient(circle at 50% 50%, rgba(26,58,110,0.3) 0%, transparent 70%)',
          pointerEvents: 'none',
        }}
      />
      <div className="grid-floor" />
      <div
        className="graph-scene"
        style={{
          position: 'absolute',
          inset: 0,
          transformStyle: 'preserve-3d',
        }}
      >
        {/* Edges */}
        {GRAPH_EDGES.map((e, i) => {
          const a = nodeMap[e.from]
          const b = nodeMap[e.to]
          if (!a || !b) return null
          const dx = b.x - a.x
          const dy = b.y - a.y
          const len = Math.sqrt(dx * dx + dy * dy)
          const angle = Math.atan2(dy, dx) * (180 / Math.PI)
          const cx = (a.x + b.x) / 2 + 210
          const cy = (a.y + b.y) / 2 + 170
          const cz = (a.z + b.z) / 2
          return (
            <div
              key={`e${i}`}
              className={e.fraud ? 'fraud-edge' : ''}
              style={{
                position: 'absolute',
                left: cx - len / 2,
                top: cy,
                width: len,
                height: e.fraud ? 1.5 : 1,
                background: e.fraud
                  ? 'linear-gradient(90deg, #FF3B30, #FFAA00)'
                  : 'rgba(148,163,184,0.18)',
                transform: `translate3d(0,0,${cz}px) rotate(${angle}deg)`,
                transformOrigin: '50% 50%',
                boxShadow: e.fraud ? '0 0 8px rgba(255,59,48,0.5)' : 'none',
              }}
            />
          )
        })}
        {/* Nodes */}
        {GRAPH_NODES.map((n, i) => (
          <div
            key={n.id}
            className="graph-node"
            style={{
              position: 'absolute',
              left: n.x + 210 - 16,
              top: n.y + 170 - 16,
              width: 32,
              height: 32,
              transform: `translate3d(0,0,${n.z}px)`,
              animationDelay: `${i * 0.25}s`,
              display: 'flex',
              alignItems: 'center',
              justifyContent: 'center',
              flexDirection: 'column',
            }}
          >
            <div
              style={{
                width: n.fraud ? 14 : 10,
                height: n.fraud ? 14 : 10,
                borderRadius: '50%',
                background: n.fraud ? '#FF3B30' : '#00FF94',
                boxShadow: n.fraud
                  ? '0 0 12px rgba(255,59,48,0.7), 0 0 24px rgba(255,59,48,0.3)'
                  : '0 0 8px rgba(0,255,148,0.4)',
              }}
            />
            <span
              style={{
                fontFamily: 'monospace',
                fontSize: 8,
                color: n.fraud ? '#FF3B30' : 'rgba(148,163,184,0.6)',
                marginTop: 3,
                letterSpacing: 0.5,
              }}
            >
              {n.id}
            </span>
          </div>
        ))}
      </div>
    </div>
  )
}

/* ═══════════════════════════════════════════════════════════════════
   TICKER
   ═══════════════════════════════════════════════════════════════════ */

function Ticker() {
  const doubled = [...TICKER_LINES, ...TICKER_LINES]
  return (
    <div
      className="ticker-panel"
      style={{
        width: 340,
        height: 200,
        overflow: 'hidden',
        background: 'rgba(0,0,0,0.7)',
        border: '1px solid #1E293B',
        padding: '12px 14px',
        position: 'relative',
        backdropFilter: 'blur(8px)',
      }}
    >
      <div className="ticker-track">
        {doubled.map((line, i) => (
          <div
            key={i}
            style={{
              fontFamily: 'monospace',
              fontSize: 11,
              color: '#00FF94',
              lineHeight: '22px',
              whiteSpace: 'nowrap',
            }}
          >
            {line}
          </div>
        ))}
      </div>
      <div
        style={{
          position: 'absolute',
          bottom: 12,
          left: 14,
          fontFamily: 'monospace',
          fontSize: 11,
          color: '#00FF94',
        }}
      >
        <span className="term-cursor" />
      </div>
      {/* Fade top/bottom */}
      <div
        style={{
          position: 'absolute',
          top: 0,
          left: 0,
          right: 0,
          height: 24,
          background: 'linear-gradient(to bottom, rgba(0,0,0,0.9), transparent)',
          pointerEvents: 'none',
        }}
      />
      <div
        style={{
          position: 'absolute',
          bottom: 0,
          left: 0,
          right: 0,
          height: 36,
          background: 'linear-gradient(to top, rgba(0,0,0,0.9), transparent)',
          pointerEvents: 'none',
        }}
      />
    </div>
  )
}

/* ═══════════════════════════════════════════════════════════════════
   TERMINAL
   ═══════════════════════════════════════════════════════════════════ */

function TerminalWidget() {
  return (
    <div
      style={{
        background: '#0A0A0A',
        border: '1px solid #1E293B',
        overflow: 'hidden',
        width: '100%',
        maxWidth: 520,
      }}
    >
      {/* Title bar */}
      <div
        style={{
          display: 'flex',
          alignItems: 'center',
          gap: 6,
          padding: '10px 14px',
          borderBottom: '1px solid #1E293B',
          background: '#0D0D0D',
        }}
      >
        <div style={{ width: 10, height: 10, borderRadius: '50%', background: '#FF3B30' }} />
        <div style={{ width: 10, height: 10, borderRadius: '50%', background: '#FFAA00' }} />
        <div style={{ width: 10, height: 10, borderRadius: '50%', background: '#00FF94' }} />
        <span
          style={{
            marginLeft: 8,
            fontFamily: 'monospace',
            fontSize: 12,
            color: '#64748B',
          }}
        >
          ews_engine.py &mdash; zsh
        </span>
      </div>
      {/* Body */}
      <div style={{ padding: '16px 14px', minHeight: 320 }}>
        {TERM_LINES.map((line, i) => {
          const isHighlight =
            line.includes('SUSPICIOUS') ||
            line.includes('HIGH_RISK') ||
            line.includes('EMPHASIS')
          return (
            <div
              key={i}
              className="term-line"
              style={{
                fontFamily: 'monospace',
                fontSize: 12.5,
                lineHeight: '24px',
                color: isHighlight ? '#FF3B30' : '#00FF94',
                animationDelay: `${i * 0.4}s`,
              }}
            >
              {line}
            </div>
          )
        })}
        <span className="term-cursor" style={{ animationDelay: `${TERM_LINES.length * 0.4}s` }} />
      </div>
    </div>
  )
}

/* ═══════════════════════════════════════════════════════════════════
   MAIN PAGE
   ═══════════════════════════════════════════════════════════════════ */

export default function LandingPage() {
  const nav = useNavigate()
  const user = useAuthStore((s) => s.user)
  const clearAuth = useAuthStore((s) => s.clearAuth)

  const handleNavAuth = async () => {
    if (user) {
      await supabase.auth.signOut()
      clearAuth()
    } else {
      nav('/auth/login')
    }
  }

  return (
    <div className="lp noise">
      <style>{STYLES}</style>

      {/* ── NAV ─────────────────────────────────────────────────── */}
      <nav
        style={{
          position: 'fixed',
          top: 0,
          left: 0,
          right: 0,
          zIndex: 50,
          display: 'flex',
          justifyContent: 'space-between',
          alignItems: 'center',
          padding: '18px 40px',
          background: 'rgba(8,12,20,0.85)',
          backdropFilter: 'blur(12px)',
          borderBottom: '1px solid rgba(30,41,59,0.5)',
        }}
      >
        <div style={{ display: 'flex', alignItems: 'baseline', gap: 3 }}>
          <span style={{ fontSize: 15, fontWeight: 800, color: '#fff', letterSpacing: -0.5 }}>
            Fin
          </span>
          <span style={{ fontSize: 15, fontWeight: 800, color: '#2563EB', letterSpacing: -0.5 }}>
            Sight
          </span>
        </div>
        <button
          onClick={handleNavAuth}
          style={{
            background: 'transparent',
            border: '1px solid #334155',
            color: '#94A3B8',
            padding: '7px 18px',
            fontSize: 11,
            fontWeight: 800,
            letterSpacing: '0.1em',
            textTransform: 'uppercase' as const,
            cursor: 'pointer',
            fontFamily: 'Inter, sans-serif',
            transition: 'border-color 0.2s, color 0.2s',
          }}
          onMouseEnter={(e) => {
            e.currentTarget.style.borderColor = '#2563EB'
            e.currentTarget.style.color = '#fff'
          }}
          onMouseLeave={(e) => {
            e.currentTarget.style.borderColor = '#334155'
            e.currentTarget.style.color = '#94A3B8'
          }}
        >
          {user ? 'Log Out' : 'Sign In'}
        </button>
      </nav>

      {/* ── HERO ────────────────────────────────────────────────── */}
      <section
        style={{
          minHeight: '100vh',
          display: 'flex',
          alignItems: 'center',
          padding: '120px 40px 60px',
          position: 'relative',
        }}
      >
        <div
          className="hero-grid"
          style={{
            display: 'flex',
            width: '100%',
            maxWidth: 1200,
            margin: '0 auto',
            gap: 40,
            alignItems: 'center',
          }}
        >
          {/* Left text */}
          <div
            className="hero-text"
            style={{ flex: 1, display: 'flex', flexDirection: 'column', gap: 0 }}
          >
            <h1
              className="hero-title"
              style={{
                fontSize: 88,
                fontWeight: 800,
                lineHeight: 0.95,
                letterSpacing: -3,
                color: '#fff',
              }}
            >
              Fin
            </h1>
            <h1
              className="hero-title"
              style={{
                fontSize: 88,
                fontWeight: 800,
                lineHeight: 0.95,
                letterSpacing: -3,
                color: '#2563EB',
              }}
            >
              Sight
            </h1>
            <p
              style={{
                marginTop: 24,
                fontSize: 16,
                fontWeight: 300,
                color: '#94A3B8',
                maxWidth: 420,
                lineHeight: 1.6,
              }}
            >
              Credit Intelligence Infrastructure for Indian NBFCs
            </p>
            <div style={{ display: 'flex', gap: 12, marginTop: 32 }}>
              <button
                onClick={() => nav('/new')}
                style={{
                  background: '#fff',
                  color: '#000',
                  border: 'none',
                  padding: '12px 28px',
                  fontSize: 13,
                  fontWeight: 800,
                  letterSpacing: '0.12em',
                  textTransform: 'uppercase' as const,
                  cursor: 'pointer',
                  fontFamily: 'Inter, sans-serif',
                  transition: 'background 0.2s, color 0.2s',
                }}
                onMouseEnter={(e) => {
                  e.currentTarget.style.background = '#2563EB'
                  e.currentTarget.style.color = '#fff'
                }}
                onMouseLeave={(e) => {
                  e.currentTarget.style.background = '#fff'
                  e.currentTarget.style.color = '#000'
                }}
              >
                Request Access
              </button>
            </div>
          </div>

          {/* Right: 3D graph + ticker */}
          <div
            style={{
              flex: 1,
              display: 'flex',
              flexDirection: 'column',
              alignItems: 'flex-end',
              gap: 20,
            }}
          >
            <FraudGraph />
            <Ticker />
          </div>
        </div>
      </section>

      {/* ── FIVE Cs FEATURE GRID ────────────────────────────────── */}
      <section style={{ padding: '100px 40px', maxWidth: 1200, margin: '0 auto' }}>
        <div style={{ marginBottom: 56 }}>
          <div
            style={{
              fontSize: 11,
              fontWeight: 800,
              textTransform: 'uppercase' as const,
              letterSpacing: '0.2em',
              color: '#00FF94',
              marginBottom: 12,
            }}
          >
            THE INTELLIGENCE STACK
          </div>
          <h2
            style={{
              fontSize: 52,
              fontWeight: 800,
              color: '#fff',
              lineHeight: 1.05,
              letterSpacing: -2,
            }}
          >
            Five Layers.
            <br />
            Zero Blind Spots.
          </h2>
        </div>

        <div
          className="features-grid"
          style={{
            display: 'grid',
            gridTemplateColumns: 'repeat(3, 1fr)',
            gap: 16,
          }}
        >
          {FEATURES.map((f) => (
            <div
              key={f.key}
              className="feature-card"
              style={{
                background: '#0D1117',
                border: '1px solid #1E293B',
                padding: '28px 24px',
                position: 'relative',
                overflow: 'hidden',
                cursor: 'default',
              }}
            >
              <div style={{ marginBottom: 16 }}>
                <CardIcon type={f.icon} color={f.color} />
              </div>
              <div
                style={{
                  fontSize: 13,
                  fontWeight: 800,
                  textTransform: 'uppercase' as const,
                  letterSpacing: '0.12em',
                  color: '#94A3B8',
                  marginBottom: 8,
                }}
              >
                {f.key}
              </div>
              <div
                style={{
                  fontSize: 28,
                  fontWeight: 800,
                  color: '#fff',
                  letterSpacing: -0.5,
                  marginBottom: 8,
                  lineHeight: 1.2,
                }}
              >
                {f.metric}
              </div>
              <div
                style={{
                  fontSize: 13,
                  color: '#64748B',
                  lineHeight: 1.55,
                }}
              >
                {f.desc}
              </div>
              <div className="card-bar" style={{ background: f.color }} />
            </div>
          ))}
        </div>
      </section>

      {/* ── PIPELINE ────────────────────────────────────────────── */}
      <section style={{ padding: '80px 40px 100px', maxWidth: 1200, margin: '0 auto' }}>
        <div style={{ textAlign: 'center', marginBottom: 64 }}>
          <div
            style={{
              fontSize: 11,
              fontWeight: 800,
              textTransform: 'uppercase' as const,
              letterSpacing: '0.2em',
              color: '#00FF94',
              marginBottom: 12,
            }}
          >
            PIPELINE
          </div>
          <h2
            style={{
              fontSize: 42,
              fontWeight: 800,
              color: '#fff',
              letterSpacing: -1.5,
            }}
          >
            From Document to Decision in 5 Stages
          </h2>
        </div>

        <div
          className="pipeline-row"
          style={{
            display: 'flex',
            alignItems: 'center',
            justifyContent: 'center',
            gap: 0,
          }}
        >
          {PIPELINE.map((step, i) => (
            <React.Fragment key={step.n}>
              {/* Step node */}
              <div
                style={{
                  display: 'flex',
                  flexDirection: 'column',
                  alignItems: 'center',
                  gap: 10,
                  minWidth: 100,
                }}
              >
                <div
                  style={{
                    width: 48,
                    height: 48,
                    borderRadius: '50%',
                    border: `1.5px solid ${step.active ? '#00FF94' : '#2563EB'}`,
                    display: 'flex',
                    alignItems: 'center',
                    justifyContent: 'center',
                    fontSize: 18,
                    fontWeight: 800,
                    color: step.active ? '#00FF94' : '#fff',
                    boxShadow: step.active ? '0 0 20px rgba(37,99,235,0.5)' : 'none',
                    transition: 'all 0.3s',
                  }}
                >
                  {step.n}
                </div>
                <div
                  style={{
                    fontSize: 11,
                    fontWeight: 800,
                    textTransform: 'uppercase' as const,
                    letterSpacing: '0.1em',
                    color: step.active ? '#00FF94' : '#94A3B8',
                  }}
                >
                  {step.name}
                </div>
                <div style={{ fontSize: 9, color: '#64748B', textTransform: 'uppercase' as const, letterSpacing: '0.05em' }}>
                  {step.desc}
                </div>
              </div>
              {/* Connector */}
              {i < PIPELINE.length - 1 && (
                <div className="pipeline-connector" style={{ width: 80, height: 2, position: 'relative' }}>
                  <svg
                    width="80"
                    height="2"
                    style={{ position: 'absolute', top: 0, left: 0 }}
                  >
                    <line
                      x1="0"
                      y1="1"
                      x2="80"
                      y2="1"
                      className="marching-line"
                      stroke="#2563EB"
                      strokeWidth="1.5"
                      fill="none"
                    />
                  </svg>
                </div>
              )}
            </React.Fragment>
          ))}
        </div>
      </section>

      {/* ── RISK TERMINAL ───────────────────────────────────────── */}
      <section style={{ background: '#050810', padding: '100px 40px' }}>
        <div
          className="ews-split"
          style={{ maxWidth: 1200, margin: '0 auto', display: 'flex', gap: 60, alignItems: 'center' }}
        >
          {/* Left text */}
          <div style={{ flex: 1 }}>
            <div
              style={{
                fontSize: 11,
                fontWeight: 800,
                textTransform: 'uppercase' as const,
                letterSpacing: '0.2em',
                color: '#00FF94',
                marginBottom: 16,
              }}
            >
              EARLY WARNING SYSTEM
            </div>
            <h2
              style={{
                fontSize: 44,
                fontWeight: 800,
                color: '#fff',
                lineHeight: 1.1,
                letterSpacing: -1.5,
                marginBottom: 40,
              }}
            >
              Catch fraud before
              <br />
              it catches you.
            </h2>
            <div style={{ display: 'flex', flexDirection: 'column', gap: 18 }}>
              {EWS_BULLETS.map((b, i) => (
                <div key={i} style={{ display: 'flex', gap: 14, alignItems: 'flex-start' }}>
                  <div
                    style={{
                      width: 2,
                      height: 14,
                      background: b.color,
                      borderRadius: 1,
                      marginTop: 3,
                      flexShrink: 0,
                    }}
                  />
                  <span style={{ fontSize: 14, color: '#94A3B8', lineHeight: 1.5, fontWeight: 300 }}>
                    {b.text}
                  </span>
                </div>
              ))}
            </div>
          </div>
          {/* Right terminal */}
          <div style={{ flex: 1, display: 'flex', justifyContent: 'flex-end' }}>
            <TerminalWidget />
          </div>
        </div>
      </section>

      {/* ── FOOTER ──────────────────────────────────────────────── */}
      <footer
        style={{
          borderTop: '1px solid #1E293B',
          padding: '32px 40px',
          display: 'flex',
          justifyContent: 'space-between',
          alignItems: 'center',
          maxWidth: 1200,
          margin: '0 auto',
        }}
      >
        <div style={{ display: 'flex', alignItems: 'baseline', gap: 3 }}>
          <span style={{ fontSize: 13, fontWeight: 800, color: '#fff' }}>Fin</span>
          <span style={{ fontSize: 13, fontWeight: 800, color: '#2563EB' }}>Sight</span>
        </div>
        <span style={{ fontSize: 11, color: '#334155' }}>
          IIT Hyderabad &middot; 2025
        </span>
      </footer>
    </div>
  )
}
