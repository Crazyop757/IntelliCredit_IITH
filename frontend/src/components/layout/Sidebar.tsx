import React, { useEffect } from 'react'
import { NavLink, useNavigate } from 'react-router-dom'
import {
  LayoutDashboard, PlusCircle, Activity, ClipboardList,
  BarChart3, Building2, ChevronLeft, ChevronRight, Zap,
} from 'lucide-react'
import { useUIStore } from '../../store/uiStore'
import { useSessionStore } from '../../store/sessionStore'
import { get } from '../../api/client'

const navItems = [
  { to: '/dashboard', label: 'Dashboard', icon: LayoutDashboard, exact: true },
  { to: '/new', label: 'New Appraisal', icon: PlusCircle },
  { to: '/companies', label: 'Companies', icon: Building2 },
]

const sessionNavItems = [
  { to: '/analysis', label: 'Live Analysis', icon: Activity },
  { to: '/qualitative', label: 'Qualitative', icon: ClipboardList },
  { to: '/results', label: 'Results', icon: BarChart3 },
]

export default function Sidebar() {
  const collapsed = useUIStore((s) => s.sidebarCollapsed)
  const setCollapsed = useUIStore((s) => s.setSidebarCollapsed)
  const apiOnline = useUIStore((s) => s.apiOnline)
  const setApiOnline = useUIStore((s) => s.setApiOnline)
  const jobId = useSessionStore((s) => s.job_id)
  const company = useSessionStore((s) => s.company)

  useEffect(() => {
    const check = async () => {
      try {
        await get('/health')
        setApiOnline(true)
      } catch {
        setApiOnline(false)
      }
    }
    check()
    const interval = setInterval(check, 30000)
    return () => clearInterval(interval)
  }, [setApiOnline])

  const hasSession = !!jobId || !!company

  return (
    <aside
      className={[
        'fixed top-0 left-0 h-full z-40 flex flex-col',
        'bg-sidebar border-r border-border-dark transition-all duration-200',
        collapsed ? 'w-16' : 'w-64',
      ].join(' ')}
    >
      {/* Logo */}
      <div className={[
        'flex items-center h-16 border-b border-border-dark px-4 flex-shrink-0',
        collapsed ? 'justify-center' : 'gap-3',
      ].join(' ')}>
        <div className="w-8 h-8 rounded-xl bg-gradient-primary flex items-center justify-center flex-shrink-0 shadow-sm">
          <span className="text-white font-bold text-xs tracking-tight">IC</span>
        </div>
        {!collapsed && (
          <div>
            <p className="text-text-primary font-bold text-sm leading-tight">IntelliCredit</p>
            <p className="text-text-muted text-[11px]">Credit Intelligence AI</p>
          </div>
        )}
      </div>

      {/* Nav */}
      <nav className="flex-1 py-3 overflow-y-auto">
        {!collapsed && (
          <p className="text-text-muted text-[10px] font-semibold uppercase tracking-widest px-5 mb-2">Main</p>
        )}
        {navItems.map((item) => (
          <NavItem key={item.to} {...item} collapsed={collapsed} />
        ))}

        {hasSession && (
          <>
            {!collapsed && (
              <p className="text-text-muted text-[10px] font-semibold uppercase tracking-widest px-5 mt-5 mb-2">
                Current Session
              </p>
            )}
            {!collapsed && <div className="mx-4 mb-2 h-px bg-border-dark" />}
            {sessionNavItems.map((item) => (
              <NavItem key={item.to} {...item} collapsed={collapsed} />
            ))}
          </>
        )}
      </nav>

      {/* Footer */}
      <div className="border-t border-border-dark p-3 space-y-1 flex-shrink-0">
        {!collapsed && (
          <div className="flex items-center gap-2 px-3 py-2 rounded-lg">
            <div className={[
              'w-2 h-2 rounded-full flex-shrink-0',
              apiOnline ? 'bg-success animate-pulse' : 'bg-danger',
            ].join(' ')} />
            <span className="text-xs text-text-secondary">{apiOnline ? 'API Online' : 'API Offline'}</span>
          </div>
        )}
        <button
          onClick={() => setCollapsed(!collapsed)}
          className="w-full flex items-center justify-center p-2 rounded-lg text-text-secondary hover:text-primary hover:bg-primary-light transition-colors"
          aria-label="Toggle sidebar"
        >
          {collapsed ? <ChevronRight size={16} /> : <ChevronLeft size={16} />}
        </button>
      </div>
    </aside>
  )
}

interface NavItemProps {
  to: string
  label: string
  icon: React.ElementType
  collapsed: boolean
  exact?: boolean
}

function NavItem({ to, label, icon: Icon, collapsed, exact = false }: NavItemProps) {
  return (
    <NavLink
      to={to}
      end={exact}
      className={({ isActive }) =>
        [
          'flex items-center mx-3 mb-0.5 rounded-lg transition-all duration-150',
          collapsed ? 'justify-center p-2.5' : 'gap-3 px-3 py-2',
          isActive
            ? 'bg-primary-light text-primary font-semibold'
            : 'text-text-secondary hover:text-text-primary hover:bg-surface2',
        ].join(' ')
      }
      title={collapsed ? label : undefined}
    >
      <Icon size={17} className="flex-shrink-0" />
      {!collapsed && <span className="text-sm">{label}</span>}
    </NavLink>
  )
}
