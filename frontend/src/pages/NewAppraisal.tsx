import React, { useState } from 'react'
import { useNavigate } from 'react-router-dom'
import { motion, AnimatePresence } from 'framer-motion'
import { useForm } from 'react-hook-form'
import { zodResolver } from '@hookform/resolvers/zod'
import { z } from 'zod'
import toast from 'react-hot-toast'
import { Building2, Upload, Rocket, ChevronRight, ChevronLeft, CheckCircle2 } from 'lucide-react'
import Input, { Select } from '../components/ui/Input'
import Button from '../components/ui/Button'
import FileDropzone from '../components/shared/FileDropzone'
import Card, { CardHeader, CardTitle, CardBody } from '../components/ui/Card'
import { runFullPipeline } from '../api/analysis'
import { useSession } from '../hooks/useSession'
import { COMPANY_TYPES, INDUSTRY_SECTORS } from '../utils/constants'

// ─── Schemas ──────────────────────────────────────────────────────────────────

const step1Schema = z.object({
  company_name: z.string().min(3, 'Company name is required'),
  cin: z.string().min(21, 'CIN must be 21 characters').max(21, 'CIN must be 21 characters'),
  loan_amount_requested: z.coerce.number().positive('Loan amount must be positive'),
  tenure_months: z.coerce.number().int().min(1).max(360),
  company_type: z.string().optional(),
  sector: z.string().optional(),
  promoter_name: z.string().optional(),
})

type Step1Form = z.infer<typeof step1Schema>

const steps = [
  { label: 'Company Details', icon: Building2 },
  { label: 'Upload Documents', icon: Upload },
  { label: 'Review & Launch', icon: Rocket },
]

// ─── Component ────────────────────────────────────────────────────────────────

export default function NewAppraisal() {
  const navigate = useNavigate()
  const { startSession, recordJob } = useSession()

  const [step, setStep] = useState(0)
  const [files, setFiles] = useState<File[]>([])
  const [isLaunching, setIsLaunching] = useState(false)
  const [formData, setFormData] = useState<Step1Form | null>(null)

  const form = useForm<Step1Form>({
    resolver: zodResolver(step1Schema),
    defaultValues: { tenure_months: 60 },
  })

  const handleStep1 = form.handleSubmit((data) => {
    setFormData(data)
    setStep(1)
  })

  const handleRemoveFile = (index: number) => {
    setFiles((prev) => prev.filter((_, i) => i !== index))
  }

  const handleLaunch = async () => {
    if (!formData) return
    if (files.length === 0) {
      toast.error('Please upload at least one document')
      return
    }

    setIsLaunching(true)
    try {
      const fd = new FormData()
      fd.append('company_name', formData.company_name)
      fd.append('cin', formData.cin)
      fd.append('loan_amount_requested', String(formData.loan_amount_requested))
      fd.append('loan_tenure_months', String(formData.tenure_months))
      if (formData.company_type) fd.append('company_type', formData.company_type)
      if (formData.sector) fd.append('sector', formData.sector)
      if (formData.promoter_name) fd.append('promoter_name', formData.promoter_name)
      // Categorise files by extension to match backend multipart field names:
      //   pdf_file  → annual report PDF
      //   bank_file → bank statement CSV/XLSX
      //   gst_files → GST JSON files (multi-file field)
      files.forEach((f) => {
        const ext = f.name.split('.').pop()?.toLowerCase() ?? ''
        if (ext === 'pdf') {
          fd.append('pdf_file', f)
        } else if (ext === 'csv' || ext === 'xlsx' || ext === 'xls') {
          fd.append('bank_file', f)
        } else if (ext === 'json') {
          fd.append('gst_files', f)
        } else {
          fd.append('pdf_file', f) // fallback
        }
      })

      const job = await runFullPipeline(fd)

      startSession(job.job_id, {
        company_name: formData.company_name,
        cin: formData.cin,
        loan_amount_requested: formData.loan_amount_requested,
        tenure_months: formData.tenure_months,
        company_type: formData.company_type,
        sector: formData.sector,
        promoter_name: formData.promoter_name,
        session_id: job.job_id,
      })
      recordJob(job.job_id)

      toast.success('Pipeline launched!')
      navigate('/analysis')
    } catch (err: any) {
      toast.error(err?.response?.data?.detail || 'Failed to launch pipeline')
    } finally {
      setIsLaunching(false)
    }
  }

  return (
    <div className="max-w-3xl mx-auto space-y-6">
      {/* Breadcrumb stepper */}
      <div className="flex items-center gap-0.5">
        {steps.map((s, i) => {
          const Icon = s.icon
          const isActive = step === i
          const isDone = step > i
          return (
            <React.Fragment key={s.label}>
              <div className={[
                'flex items-center gap-2 px-3 py-2 rounded-lg text-sm font-medium transition-all',
                isActive ? 'bg-primary/15 text-primary' : isDone ? 'text-success' : 'text-text-muted',
              ].join(' ')}>
                {isDone ? <CheckCircle2 size={16} /> : <Icon size={16} />}
                <span className={isActive || isDone ? '' : 'hidden sm:inline'}>{s.label}</span>
              </div>
              {i < steps.length - 1 && (
                <ChevronRight size={14} className="text-text-muted mx-0.5" />
              )}
            </React.Fragment>
          )
        })}
      </div>

      <AnimatePresence mode="wait">
        {/* Step 1: Company Details */}
        {step === 0 && (
          <motion.div
            key="step1"
            initial={{ opacity: 0, x: 20 }}
            animate={{ opacity: 1, x: 0 }}
            exit={{ opacity: 0, x: -20 }}
            transition={{ duration: 0.2 }}
          >
            <Card>
              <CardHeader>
                <CardTitle
                  icon={<Building2 size={18} className="text-primary" />}
                  description="Basic information about the borrower"
                >
                  Company Details
                </CardTitle>
              </CardHeader>
              <CardBody>
                <form onSubmit={handleStep1} className="space-y-5">
                  <div className="grid grid-cols-1 sm:grid-cols-2 gap-4">
                    <Input
                      label="Company Name *"
                      placeholder="Reliance Industries Ltd"
                      {...form.register('company_name')}
                      error={form.formState.errors.company_name?.message}
                    />
                    <Input
                      label="CIN (21 chars) *"
                      placeholder="L17110MH1973PLC019786"
                      {...form.register('cin')}
                      error={form.formState.errors.cin?.message}
                      hint="Corporate Identity Number"
                    />
                    <Input
                      label="Loan Amount Requested (₹ Cr) *"
                      type="number"
                      placeholder="100"
                      {...form.register('loan_amount_requested')}
                      error={form.formState.errors.loan_amount_requested?.message}
                    />
                    <Input
                      label="Tenure (months) *"
                      type="number"
                      placeholder="60"
                      {...form.register('tenure_months')}
                      error={form.formState.errors.tenure_months?.message}
                    />
                    <Select
                      label="Company Type"
                      options={[...COMPANY_TYPES] as { value: string; label: string }[]}
                      placeholder="Select type…"
                      {...form.register('company_type')}
                    />
                    <Select
                      label="Sector"
                      options={[...INDUSTRY_SECTORS] as { value: string; label: string }[]}
                      placeholder="Select sector…"
                      {...form.register('sector')}
                    />
                  </div>
                  <Input
                    label="Promoter / Director Name"
                    placeholder="Mukesh Ambani"
                    {...form.register('promoter_name')}
                  />
                  <div className="flex justify-end pt-2">
                    <Button type="submit" iconRight={<ChevronRight size={16} />}>
                      Next: Upload Documents
                    </Button>
                  </div>
                </form>
              </CardBody>
            </Card>
          </motion.div>
        )}

        {/* Step 2: Upload */}
        {step === 1 && (
          <motion.div
            key="step2"
            initial={{ opacity: 0, x: 20 }}
            animate={{ opacity: 1, x: 0 }}
            exit={{ opacity: 0, x: -20 }}
            transition={{ duration: 0.2 }}
          >
            <Card>
              <CardHeader>
                <CardTitle
                  icon={<Upload size={18} className="text-primary" />}
                  description="Annual reports, bank statements, and GST data"
                >
                  Upload Documents
                </CardTitle>
              </CardHeader>
              <CardBody className="space-y-6">
                <FileDropzone
                  files={files}
                  onFiles={(f) => setFiles((p) => [...p, ...f])}
                  onRemove={handleRemoveFile}
                  label="Drop annual reports, bank statements, or GST files"
                  hint="PDF, CSV, and JSON supported — up to 50 MB each"
                  accept={{
                    'application/pdf': ['.pdf'],
                    'text/csv': ['.csv'],
                    'application/json': ['.json'],
                  }}
                />
                <div className="flex items-center justify-between">
                  <div className="text-xs text-text-muted">
                    <p className="font-medium text-text-secondary mb-0.5">Accepted document types:</p>
                    <ul className="space-y-0.5">
                      <li>📄 Annual Reports (PDF)</li>
                      <li>📊 Bank Statements (CSV)</li>
                      <li>🗂️ GST Returns (JSON)</li>
                    </ul>
                  </div>
                  <div className="flex gap-3">
                    <Button variant="ghost" icon={<ChevronLeft size={16} />} onClick={() => setStep(0)}>
                      Back
                    </Button>
                    <Button
                      iconRight={<ChevronRight size={16} />}
                      onClick={() => {
                        if (files.length === 0) {
                          toast.error('Add at least one document')
                          return
                        }
                        setStep(2)
                      }}
                    >
                      Review
                    </Button>
                  </div>
                </div>
              </CardBody>
            </Card>
          </motion.div>
        )}

        {/* Step 3: Review & Launch */}
        {step === 2 && formData && (
          <motion.div
            key="step3"
            initial={{ opacity: 0, x: 20 }}
            animate={{ opacity: 1, x: 0 }}
            exit={{ opacity: 0, x: -20 }}
            transition={{ duration: 0.2 }}
          >
            <Card>
              <CardHeader>
                <CardTitle
                  icon={<Rocket size={18} className="text-primary" />}
                  description="Confirm details and start the AI pipeline"
                >
                  Review &amp; Launch
                </CardTitle>
              </CardHeader>
              <CardBody className="space-y-6">
                {/* Summary */}
                <div className="bg-surface2 rounded-xl p-4 space-y-3">
                  <h4 className="text-text-secondary text-xs font-semibold uppercase tracking-wider mb-2">
                    Company Summary
                  </h4>
                  <div className="grid grid-cols-2 gap-3 text-sm">
                    {[
                      { label: 'Company', value: formData.company_name },
                      { label: 'CIN', value: formData.cin },
                      { label: 'Loan Amount', value: `₹${formData.loan_amount_requested} Cr` },
                      { label: 'Tenure', value: `${formData.tenure_months} months` },
                      { label: 'Type', value: formData.company_type || '—' },
                      { label: 'Sector', value: formData.sector || '—' },
                    ].map(({ label, value }) => (
                      <div key={label}>
                        <p className="text-text-muted text-xs">{label}</p>
                        <p className="text-text-primary font-medium mt-0.5">{value}</p>
                      </div>
                    ))}
                  </div>
                </div>

                <div className="bg-surface2 rounded-xl p-4">
                  <h4 className="text-text-secondary text-xs font-semibold uppercase tracking-wider mb-2">
                    {files.length} Document{files.length !== 1 ? 's' : ''} to Process
                  </h4>
                  <ul className="space-y-1.5">
                    {files.map((f, i) => (
                      <li key={i} className="flex items-center gap-2 text-sm text-text-secondary">
                        <CheckCircle2 size={13} className="text-success flex-shrink-0" />
                        {f.name}
                      </li>
                    ))}
                  </ul>
                </div>

                <div className="bg-primary/8 border border-primary/25 rounded-xl p-4">
                  <p className="text-primary text-sm font-medium mb-1">Pipeline Stages</p>
                  <p className="text-text-secondary text-xs">
                    Ingest → GST Analysis → Research Agent → Credit Scoring → CAM Generation
                  </p>
                  <p className="text-text-muted text-xs mt-1">Estimated time: 3–8 minutes</p>
                </div>

                <div className="flex items-center justify-between">
                  <Button variant="ghost" icon={<ChevronLeft size={16} />} onClick={() => setStep(1)}>
                    Back
                  </Button>
                  <Button
                    icon={<Rocket size={16} />}
                    loading={isLaunching}
                    onClick={handleLaunch}
                  >
                    Launch Pipeline
                  </Button>
                </div>
              </CardBody>
            </Card>
          </motion.div>
        )}
      </AnimatePresence>
    </div>
  )
}
