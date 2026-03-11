import React, { useState } from 'react'
import { useNavigate } from 'react-router-dom'
import { useForm } from 'react-hook-form'
import { zodResolver } from '@hookform/resolvers/zod'
import { z } from 'zod'
import toast from 'react-hot-toast'
import { Eye, EyeOff, Zap } from 'lucide-react'
import { supabase } from '../../lib/supabase'

const schema = z.object({
  password: z.string().min(8, 'Password must be at least 8 characters'),
  confirm: z.string(),
}).refine((d) => d.password === d.confirm, {
  message: 'Passwords do not match',
  path: ['confirm'],
})
type FormData = z.infer<typeof schema>

export default function ResetPasswordPage() {
  const navigate = useNavigate()
  const [showPw, setShowPw] = useState(false)
  const [loading, setLoading] = useState(false)

  const { register, handleSubmit, formState: { errors } } = useForm<FormData>({
    resolver: zodResolver(schema),
  })

  const onSubmit = async (data: FormData) => {
    setLoading(true)
    try {
      const { error } = await supabase.auth.updateUser({ password: data.password })
      if (error) {
        toast.error(error.message)
        return
      }
      toast.success('Password updated successfully!')
      navigate('/dashboard', { replace: true })
    } finally {
      setLoading(false)
    }
  }

  return (
    <div className="min-h-screen bg-[#080C14] flex items-center justify-center px-4">
      <div className="w-full max-w-md">
        <div className="flex items-center gap-3 mb-8 justify-center">
          <div className="w-10 h-10 rounded-xl bg-gradient-primary flex items-center justify-center shadow-lg">
            <Zap size={20} className="text-white" />
          </div>
          <span className="text-white font-bold text-xl tracking-tight">FinSight</span>
        </div>

        <div className="bg-surface rounded-2xl border border-border-dark p-8 shadow-xl">
          <h1 className="text-text-primary font-bold text-2xl mb-1">Set new password</h1>
          <p className="text-text-muted text-sm mb-6">Choose a strong password for your account.</p>

          <form onSubmit={handleSubmit(onSubmit)} className="space-y-4">
            <div>
              <label className="block text-text-secondary text-sm font-medium mb-1.5">New password</label>
              <div className="relative">
                <input
                  {...register('password')}
                  type={showPw ? 'text' : 'password'}
                  autoComplete="new-password"
                  placeholder="••••••••"
                  className="w-full bg-surface2 border border-border-dark rounded-lg px-3.5 py-2.5 pr-10 text-text-primary placeholder-text-muted text-sm focus:outline-none focus:border-primary transition-colors"
                />
                <button
                  type="button"
                  onClick={() => setShowPw(!showPw)}
                  className="absolute right-3 top-1/2 -translate-y-1/2 text-text-muted hover:text-text-secondary"
                >
                  {showPw ? <EyeOff size={16} /> : <Eye size={16} />}
                </button>
              </div>
              {errors.password && <p className="text-danger text-xs mt-1">{errors.password.message}</p>}
            </div>

            <div>
              <label className="block text-text-secondary text-sm font-medium mb-1.5">Confirm password</label>
              <input
                {...register('confirm')}
                type="password"
                autoComplete="new-password"
                placeholder="••••••••"
                className="w-full bg-surface2 border border-border-dark rounded-lg px-3.5 py-2.5 text-text-primary placeholder-text-muted text-sm focus:outline-none focus:border-primary transition-colors"
              />
              {errors.confirm && <p className="text-danger text-xs mt-1">{errors.confirm.message}</p>}
            </div>

            <button
              type="submit"
              disabled={loading}
              className="w-full bg-primary hover:bg-primary-dark text-white font-semibold py-2.5 rounded-lg transition-colors disabled:opacity-60 mt-2"
            >
              {loading ? 'Updating…' : 'Update password'}
            </button>
          </form>
        </div>
      </div>
    </div>
  )
}
