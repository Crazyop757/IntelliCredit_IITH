import React, { useState } from 'react'
import { Link } from 'react-router-dom'
import { useForm } from 'react-hook-form'
import { zodResolver } from '@hookform/resolvers/zod'
import { z } from 'zod'
import toast from 'react-hot-toast'
import { ArrowLeft, Zap } from 'lucide-react'
import { supabase } from '../../lib/supabase'

const schema = z.object({
  email: z.string().email('Valid email required'),
})
type FormData = z.infer<typeof schema>

export default function ForgotPasswordPage() {
  const [sent, setSent] = useState(false)
  const [loading, setLoading] = useState(false)

  const { register, handleSubmit, formState: { errors } } = useForm<FormData>({
    resolver: zodResolver(schema),
  })

  const onSubmit = async (data: FormData) => {
    setLoading(true)
    try {
      const { error } = await supabase.auth.resetPasswordForEmail(data.email, {
        redirectTo: `${window.location.origin}/auth/reset-password`,
      })
      if (error) {
        toast.error(error.message)
        return
      }
      setSent(true)
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
          {sent ? (
            <div className="text-center py-4">
              <div className="w-12 h-12 rounded-full bg-success/10 flex items-center justify-center mx-auto mb-4">
                <span className="text-success text-2xl">✓</span>
              </div>
              <h2 className="text-text-primary font-bold text-xl mb-2">Check your email</h2>
              <p className="text-text-muted text-sm mb-6">
                We sent a password reset link to your email address.
              </p>
              <Link to="/auth/login" className="text-primary hover:underline text-sm">
                Back to sign in
              </Link>
            </div>
          ) : (
            <>
              <Link to="/auth/login" className="flex items-center gap-2 text-text-muted hover:text-text-secondary text-sm mb-6 transition-colors">
                <ArrowLeft size={14} /> Back to sign in
              </Link>
              <h1 className="text-text-primary font-bold text-2xl mb-1">Reset password</h1>
              <p className="text-text-muted text-sm mb-6">
                Enter your email and we'll send you a reset link.
              </p>
              <form onSubmit={handleSubmit(onSubmit)} className="space-y-4">
                <div>
                  <label className="block text-text-secondary text-sm font-medium mb-1.5">Email</label>
                  <input
                    {...register('email')}
                    type="email"
                    autoComplete="email"
                    placeholder="you@company.com"
                    className="w-full bg-surface2 border border-border-dark rounded-lg px-3.5 py-2.5 text-text-primary placeholder-text-muted text-sm focus:outline-none focus:border-primary transition-colors"
                  />
                  {errors.email && <p className="text-danger text-xs mt-1">{errors.email.message}</p>}
                </div>
                <button
                  type="submit"
                  disabled={loading}
                  className="w-full bg-primary hover:bg-primary-dark text-white font-semibold py-2.5 rounded-lg transition-colors disabled:opacity-60"
                >
                  {loading ? 'Sending…' : 'Send reset link'}
                </button>
              </form>
            </>
          )}
        </div>
      </div>
    </div>
  )
}
