import React from 'react'
import { Navigate, useLocation } from 'react-router-dom'
import { useAuthStore } from '../../store/authStore'

interface Props {
  children: React.ReactNode
}

/**
 * Wrap any route element with this to require authentication.
 * Unauthenticated users are redirected to /auth/login with `?from=<originalPath>`.
 */
export default function ProtectedRoute({ children }: Props) {
  const session = useAuthStore((s) => s.session)
  const isLoading = useAuthStore((s) => s.isLoading)
  const location = useLocation()

  if (isLoading) {
    return (
      <div className="min-h-screen bg-[#080C14] flex items-center justify-center">
        <div className="w-8 h-8 border-2 border-primary border-t-transparent rounded-full animate-spin" />
      </div>
    )
  }

  if (!session) {
    return <Navigate to="/auth/login" state={{ from: location.pathname }} replace />
  }

  return <>{children}</>
}
