import React from 'react'
import { useLocation, useNavigate } from 'react-router-dom'
import { ArrowLeft, RefreshCw } from 'lucide-react'
import { useSessionStore } from '../../store/sessionStore'

const titleMap: Record<string, string> = {
  '/dashboard': 'Dashboard',
  '/new': 'New Appraisal',
  '/analysis': 'Live Analysis',
  '/qualitative': 'Qualitative Assessment',
  '/results': 'Credit Results',
  '/companies': 'Companies',
}

export default function TopBar() {
  const location = useLocation()
  const navigate = useNavigate()
  const company = useSessionStore((s) => s.company)
  const reset = useSessionStore((s) => s.reset)

  const isCompanyDetail = location.pathname.startsWith('/companies/')
  const showBack = ['/analysis', '/qualitative', '/results'].includes(location.pathname) || isCompanyDetail

  let title = titleMap[location.pathname] || 'IntelliCredit'
  if (isCompanyDetail) title = 'Company Detail'

  const handleNewAppraisal = () => {
    reset()
    navigate('/new')
  }

  return (
    <header className="h-16 bg-surface border-b border-border-dark flex items-center justify-between px-6 sticky top-0 z-30">
      <div className="flex items-center gap-3">
        {showBack && (
          <button
            onClick={() => navigate(-1)}
            className="text-text-muted hover:text-text-primary transition-colors p-1.5 rounded-lg hover:bg-surface2"
          >
            <ArrowLeft size={16} />
          </button>
        )}
        <div>
          <h1 className="text-text-primary font-semibold text-sm leading-none">{title}</h1>
          {company && ['/analysis', '/qualitative', '/results'].includes(location.pathname) && (
            <p className="text-text-muted text-xs mt-0.5">{company.company_name}</p>
          )}
        </div>
      </div>

      <div className="flex items-center gap-2">
        {location.pathname === '/results' && (
          <button
            onClick={handleNewAppraisal}
            className="flex items-center gap-2 text-xs text-text-secondary hover:text-primary transition-colors px-3 py-1.5 rounded-lg border border-border-dark hover:border-primary/40 hover:bg-primary-light"
          >
            <RefreshCw size={13} />
            New Appraisal
          </button>
        )}

      </div>
    </header>
  )
}
