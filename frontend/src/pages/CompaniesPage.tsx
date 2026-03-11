import React, { useState } from 'react'
import { useNavigate } from 'react-router-dom'
import { useQuery } from '@tanstack/react-query'
import { motion } from 'framer-motion'
import { Search, Plus, Building2 } from 'lucide-react'
import { listCompanies } from '../api/companies'
import Card, { CardBody } from '../components/ui/Card'
import { RiskBandBadge, DecisionBadge } from '../components/ui/Badge'
import Input from '../components/ui/Input'
import Button from '../components/ui/Button'
import { TableSkeleton } from '../components/ui/Skeleton'
import { formatDate } from '../utils/formatters'

export default function CompaniesPage() {
  const navigate = useNavigate()
  const [search, setSearch] = useState('')

  const { data, isLoading } = useQuery({
    queryKey: ['companies'],
    queryFn: listCompanies,
    staleTime: 30_000,
  })

  const filtered = (data?.companies ?? []).filter((c) =>
    (c.company_name ?? '').toLowerCase().includes(search.toLowerCase()) ||
    c.company_id.toLowerCase().includes(search.toLowerCase()),
  )

  return (
    <div className="max-w-6xl mx-auto space-y-5">
      {/* Toolbar */}
      <div className="flex flex-col sm:flex-row gap-3 items-start sm:items-center">
        <div className="relative flex-1 max-w-sm">
          <Search size={15} className="absolute left-3 top-1/2 -translate-y-1/2 text-text-muted pointer-events-none" />
          <Input
            value={search}
            onChange={(e: React.ChangeEvent<HTMLInputElement>) => setSearch(e.target.value)}
            placeholder="Search company name or CIN…"
            className="pl-9"
          />
        </div>
        <Button icon={<Plus size={14} />} onClick={() => navigate('/new')}>
          New Appraisal
        </Button>
      </div>

      <Card>
        <CardBody className="p-0">
          {isLoading ? (
            <div className="p-6">
              <TableSkeleton rows={6} cols={5} />
            </div>
          ) : filtered.length === 0 ? (
            <div className="flex flex-col items-center justify-center py-20 text-center px-6">
              <Building2 size={40} className="text-text-muted mb-3" />
              <h3 className="text-text-primary font-semibold mb-1">
                {search ? 'No matching companies' : 'No companies appraised yet'}
              </h3>
              <p className="text-text-secondary text-sm mb-5">
                {search
                  ? 'Try a different search term'
                  : 'Start a new appraisal to onboard your first company.'}
              </p>
              {!search && (
                <Button icon={<Plus size={14} />} onClick={() => navigate('/new')}>
                  Run First Appraisal
                </Button>
              )}
            </div>
          ) : (
            <div className="overflow-x-auto">
              <table className="w-full text-sm">
                <thead>
                  <tr className="border-b border-border-dark">
                    {['Company', 'CIN', 'Risk Band', 'Decision', 'Last Appraised', ''].map((h) => (
                      <th
                        key={h}
                        className="text-left text-text-muted font-medium px-5 py-3.5 text-xs uppercase tracking-wide"
                      >
                        {h}
                      </th>
                    ))}
                  </tr>
                </thead>
                <tbody>
                  {filtered.map((c, i) => (
                    <motion.tr
                      key={c.company_id}
                      initial={{ opacity: 0, y: 6 }}
                      animate={{ opacity: 1, y: 0 }}
                      transition={{ delay: i * 0.03 }}
                      onClick={() => navigate(`/companies/${c.company_id}`)}
                      className="border-b border-border-dark/40 hover:bg-surface2/60 cursor-pointer group transition-colors last:border-0"
                    >
                      <td className="px-5 py-4">
                        <p className="text-text-primary font-medium group-hover:text-primary transition-colors">
                          {c.company_name ?? c.company_id}
                        </p>
                      </td>
                      <td className="px-5 py-4 text-text-secondary font-mono text-xs">
                        {c.company_id}
                      </td>
                      <td className="px-5 py-4">
                        {c.risk_band ? <RiskBandBadge band={c.risk_band} /> : <span className="text-text-muted">—</span>}
                      </td>
                      <td className="px-5 py-4">
                        {c.decision ? <DecisionBadge decision={c.decision} /> : <span className="text-text-muted">—</span>}
                      </td>
                      <td className="px-5 py-4 text-text-muted text-xs">
                        {c.appraisal_date ? formatDate(c.appraisal_date) : '—'}
                      </td>
                      <td className="px-5 py-4 text-right opacity-0 group-hover:opacity-100 transition-opacity">
                        <span className="text-primary text-xs font-medium">View →</span>
                      </td>
                    </motion.tr>
                  ))}
                </tbody>
              </table>
            </div>
          )}
        </CardBody>
      </Card>

      <p className="text-text-muted text-xs text-right">
        {filtered.length} {filtered.length === 1 ? 'company' : 'companies'}{search ? ' matching' : ` of ${data?.total ?? 0} total`}
      </p>
    </div>
  )
}
