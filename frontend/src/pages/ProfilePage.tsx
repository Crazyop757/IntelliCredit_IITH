import React, { useEffect, useState } from 'react'
import { useForm } from 'react-hook-form'
import { zodResolver } from '@hookform/resolvers/zod'
import { z } from 'zod'
import toast from 'react-hot-toast'
import { motion } from 'framer-motion'
import { User, Mail, Edit3, LogOut, Save, X, Loader2, Shield, Key } from 'lucide-react'
import { supabase } from '../lib/supabase'
import { useAuthStore } from '../store/authStore'
import apiClient from '../api/client'

const profileSchema = z.object({
  full_name: z.string().min(2, 'Name must be at least 2 characters').max(80, 'Name too long'),
})

type ProfileForm = z.infer<typeof profileSchema>

export default function ProfilePage() {
  const { user, setUser, clearAuth } = useAuthStore()
  const [isEditing, setIsEditing] = useState(false)
  const [isUpdating, setIsUpdating] = useState(false)
  const [isSigningOut, setIsSigningOut] = useState(false)

  const fullName: string = (user?.user_metadata?.full_name as string) ?? user?.email?.split('@')[0] ?? 'User'
  const email = user?.email ?? ''
  const initials = fullName
    .split(' ')
    .slice(0, 2)
    .map((n) => n[0]?.toUpperCase() ?? '')
    .join('')

  const {
    register,
    handleSubmit,
    reset,
    formState: { errors },
  } = useForm<ProfileForm>({
    resolver: zodResolver(profileSchema),
    defaultValues: { full_name: fullName },
  })

  useEffect(() => {
    reset({ full_name: fullName })
  }, [fullName, reset])

  async function onSubmit(values: ProfileForm) {
    setIsUpdating(true)
    try {
      await apiClient.patch('/auth/profile', { full_name: values.full_name })
      // Also update local Supabase session metadata via JS client
      const { data, error } = await supabase.auth.updateUser({
        data: { full_name: values.full_name },
      })
      if (error) throw error
      if (data.user) setUser(data.user)
      toast.success('Profile updated')
      setIsEditing(false)
    } catch (err: unknown) {
      const msg = err instanceof Error ? err.message : 'Failed to update profile'
      toast.error(msg)
    } finally {
      setIsUpdating(false)
    }
  }

  async function handleSignOut() {
    setIsSigningOut(true)
    try {
      await supabase.auth.signOut()
      clearAuth()
      window.location.href = '/auth/login'
    } catch {
      toast.error('Sign out failed')
      setIsSigningOut(false)
    }
  }

  return (
    <div className="max-w-2xl space-y-6">
      {/* Page header */}
      <div>
        <h1 className="text-xl font-bold text-white">Profile</h1>
        <p className="text-sm text-slate-400 mt-0.5">Manage your account details</p>
      </div>

      {/* Avatar + identity card */}
      <motion.div
        initial={{ opacity: 0, y: 8 }}
        animate={{ opacity: 1, y: 0 }}
        className="p-6 rounded-2xl bg-slate-900/60 border border-slate-700/50 space-y-6"
      >
        {/* Avatar row */}
        <div className="flex items-center gap-5">
          <div className="w-16 h-16 rounded-2xl bg-gradient-to-br from-sky-500 to-indigo-600 flex items-center justify-center text-white text-xl font-bold shadow-lg select-none">
            {initials}
          </div>
          <div>
            <h2 className="text-base font-semibold text-white">{fullName}</h2>
            <p className="text-sm text-slate-400">{email}</p>
          </div>
        </div>

        {/* Divider */}
        <div className="border-t border-slate-700/50" />

        {/* Edit form / display */}
        {isEditing ? (
          <form onSubmit={handleSubmit(onSubmit)} className="space-y-4">
            <div>
              <label className="block text-xs font-medium text-slate-400 mb-1.5">Full name</label>
              <input
                {...register('full_name')}
                className="w-full px-3 py-2 text-sm bg-slate-800/60 border border-slate-600 rounded-lg text-white placeholder-slate-500 focus:outline-none focus:border-sky-500 transition-colors"
                placeholder="Your full name"
                autoFocus
              />
              {errors.full_name && (
                <p className="mt-1 text-xs text-red-400">{errors.full_name.message}</p>
              )}
            </div>

            <div className="flex items-center gap-3">
              <button
                type="submit"
                disabled={isUpdating}
                className="flex items-center gap-2 px-4 py-2 text-sm font-medium bg-sky-600 hover:bg-sky-500 text-white rounded-lg transition-colors disabled:opacity-60"
              >
                {isUpdating ? <Loader2 className="w-3.5 h-3.5 animate-spin" /> : <Save className="w-3.5 h-3.5" />}
                Save changes
              </button>
              <button
                type="button"
                onClick={() => { setIsEditing(false); reset({ full_name: fullName }) }}
                className="flex items-center gap-2 px-4 py-2 text-sm text-slate-400 hover:text-white border border-slate-700 hover:border-slate-500 rounded-lg transition-colors"
              >
                <X className="w-3.5 h-3.5" />
                Cancel
              </button>
            </div>
          </form>
        ) : (
          <div className="space-y-4">
            <InfoRow icon={User} label="Full name" value={fullName} />
            <InfoRow icon={Mail} label="Email address" value={email} />

            <button
              onClick={() => setIsEditing(true)}
              className="flex items-center gap-2 px-4 py-2 text-sm text-slate-300 hover:text-white border border-slate-700 hover:border-sky-500/50 rounded-lg transition-colors"
            >
              <Edit3 className="w-3.5 h-3.5" />
              Edit profile
            </button>
          </div>
        )}
      </motion.div>

      {/* Security section */}
      <motion.div
        initial={{ opacity: 0, y: 8 }}
        animate={{ opacity: 1, y: 0 }}
        transition={{ delay: 0.08 }}
        className="p-6 rounded-2xl bg-slate-900/60 border border-slate-700/50 space-y-4"
      >
        <div className="flex items-center gap-2 mb-4">
          <Shield className="w-4 h-4 text-slate-400" />
          <h3 className="text-sm font-semibold text-white">Security</h3>
        </div>

        <div className="flex items-center justify-between p-3 rounded-xl bg-slate-800/40 border border-slate-700/30">
          <div className="flex items-center gap-3">
            <Key className="w-4 h-4 text-slate-400" />
            <div>
              <p className="text-sm text-white">Password</p>
              <p className="text-xs text-slate-500">Change your account password</p>
            </div>
          </div>
          <a
            href="/auth/forgot-password"
            className="text-xs text-sky-400 hover:text-sky-300 transition-colors"
          >
            Reset
          </a>
        </div>
      </motion.div>

      {/* Sign out */}
      <motion.div
        initial={{ opacity: 0, y: 8 }}
        animate={{ opacity: 1, y: 0 }}
        transition={{ delay: 0.12 }}
      >
        <button
          onClick={handleSignOut}
          disabled={isSigningOut}
          className="flex items-center gap-2 px-4 py-2 text-sm font-medium text-red-400 hover:text-red-300 border border-red-400/20 hover:border-red-400/40 hover:bg-red-400/5 rounded-lg transition-colors disabled:opacity-50"
        >
          {isSigningOut ? <Loader2 className="w-4 h-4 animate-spin" /> : <LogOut className="w-4 h-4" />}
          Sign out
        </button>
      </motion.div>
    </div>
  )
}

function InfoRow({ icon: Icon, label, value }: { icon: React.ElementType; label: string; value: string }) {
  return (
    <div className="flex items-center gap-3">
      <div className="w-8 h-8 rounded-lg bg-slate-800/60 flex items-center justify-center shrink-0">
        <Icon className="w-3.5 h-3.5 text-slate-400" />
      </div>
      <div>
        <p className="text-[11px] text-slate-500 uppercase tracking-wide font-medium">{label}</p>
        <p className="text-sm text-white">{value}</p>
      </div>
    </div>
  )
}
