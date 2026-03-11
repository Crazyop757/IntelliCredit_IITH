import React from 'react'
import { Building2, Calendar, Hash } from 'lucide-react'
import type { Company } from '../../store/types'
import { formatDate } from '../../utils/formatters'

interface CompanyHeaderProps {
  company: Company
  subtitle?: string
  children?: React.ReactNode
}

export default function CompanyHeader({ company, subtitle, children }: CompanyHeaderProps) {
  return (
    <div className="bg-surface border border-border-dark rounded-2xl p-6">
      <div className="flex items-start justify-between gap-4">
        <div className="flex items-start gap-4">
          <div className="w-12 h-12 rounded-xl bg-primary/15 flex items-center justify-center flex-shrink-0">
            <Building2 size={22} className="text-primary" />
          </div>
          <div>
            <h2 className="text-text-primary text-xl font-bold leading-tight">{company.company_name}</h2>
            {subtitle && <p className="text-text-secondary text-sm mt-0.5">{subtitle}</p>}
            <div className="flex flex-wrap items-center gap-3 mt-2">
              {company.cin && (
                <div className="flex items-center gap-1.5 text-text-muted text-xs">
                  <Hash size={12} />
                  <span className="font-mono">{company.cin}</span>
                </div>
              )}
              {company.company_type && (
                <span className="text-text-muted text-xs">{company.company_type}</span>
              )}
              {company.sector && (
                <span className="text-xs px-2 py-0.5 rounded-full bg-accent/10 text-accent border border-accent/20">
                  {company.sector}
                </span>
              )}
              {company.created_at && (
                <div className="flex items-center gap-1.5 text-text-muted text-xs">
                  <Calendar size={12} />
                  <span>{formatDate(company.created_at)}</span>
                </div>
              )}
            </div>
          </div>
        </div>
        {children && <div className="flex items-center gap-2 flex-shrink-0">{children}</div>}
      </div>
    </div>
  )
}
