import React, { useEffect, useState } from 'react'
import { NavLink, useNavigate } from 'react-router-dom'
import {
  LayoutDashboard, PlusCircle,
  Building2, ChevronLeft, ChevronRight, History, User, LogOut,
} from 'lucide-react'
import { useUIStore } from '../../store/uiStore'
import { useSessionStore } from '../../store/sessionStore'
import { useAuthStore } from '../../store/authStore'
import { supabase } from '../../lib/supabase'
import { get } from '../../api/client'

const navItems = [
  { to: '/dashboard', label: 'Dashboard', icon: LayoutDashboard, exact: true },
  { to: '/new', label: 'New Appraisal', icon: PlusCircle },
  { to: '/history', label: 'History', icon: History },
  { to: '/companies', label: 'Companies', icon: Building2 },
  { to: '/profile', label: 'Profile', icon: User },
]

export default function Sidebar() {
  const collapsed = useUIStore((s) => s.sidebarCollapsed)
  const setCollapsed = useUIStore((s) => s.setSidebarCollapsed)
  const apiOnline = useUIStore((s) => s.apiOnline)
  const setApiOnline = useUIStore((s) => s.setApiOnline)
  const clearAuth = useAuthStore((s) => s.clearAuth)
  const navigate = useNavigate()
  const [signingOut, setSigningOut] = useState(false)

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

  async function handleLogout() {
    setSigningOut(true)
    try {
      await supabase.auth.signOut()
    } finally {
      clearAuth()
      setSigningOut(false)
      navigate('/')
    }
  }

  return (
    <aside
      className={[
        'fixed top-0 left-0 h-full z-40 flex flex-col',
        'bg-sidebar border-r border-border-dark transition-all duration-200',
        collapsed ? 'w-16' : 'w-64',
      ].join(' ')}
    >
      {/* Logo — click to return to landing page */}
      <NavLink
        to="/"
        className={[
          'flex items-center h-16 border-b border-border-dark px-4 flex-shrink-0 group',
          collapsed ? 'justify-center' : 'gap-3',
        ].join(' ')}
        title="Back to Home"
      >
        {collapsed ? (
          <div style={{ display: 'flex', alignItems: 'baseline', gap: 1 }}>
            <span style={{ fontSize: 14, fontWeight: 800, color: '#fff', letterSpacing: -0.5 }}>F</span>
            <span style={{ fontSize: 14, fontWeight: 800, color: '#2563EB', letterSpacing: -0.5 }}>S</span>
          </div>
        ) : (
          <div>
            <div style={{ display: 'flex', alignItems: 'baseline', gap: 2 }}>
              <span style={{ fontSize: 15, fontWeight: 800, color: '#fff', letterSpacing: -0.5 }}>Fin</span>
              <span style={{ fontSize: 15, fontWeight: 800, color: '#2563EB', letterSpacing: -0.5 }}>Sight</span>
            </div>
            <p className="text-text-muted text-[11px]">Credit Intelligence AI</p>
          </div>
        )}
      </NavLink>

      {/* Nav */}
      <nav className="flex-1 py-3 overflow-y-auto">
        {!collapsed && (
          <p className="text-text-muted text-[10px] font-semibold uppercase tracking-widest px-5 mb-2">Main</p>
        )}
        {navItems.map((item) => (
          <NavItem key={item.to} {...item} collapsed={collapsed} />
        ))}
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
          onClick={handleLogout}
          disabled={signingOut}
          className="w-full flex items-center gap-2 px-3 py-2 rounded-lg text-text-secondary hover:text-red-400 hover:bg-red-500/10 transition-colors"
          aria-label="Log out"
          title={collapsed ? 'Log out' : undefined}
        >
          <LogOut size={15} className="flex-shrink-0" />
          {!collapsed && <span className="text-sm">{signingOut ? 'Signing out…' : 'Log out'}</span>}
        </button>
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
