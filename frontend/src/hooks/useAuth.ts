import { useEffect } from 'react'
import { supabase } from '../lib/supabase'
import { useAuthStore } from '../store/authStore'
import { useSessionStore } from '../store/sessionStore'

/**
 * Subscribes to Supabase auth state changes and keeps authStore in sync.
 * Also clears the appraisal session when the user signs out or switches accounts.
 * Call once at app root (inside App.tsx).
 */
export function useAuth() {
  const setSession = useAuthStore((s) => s.setSession)
  const setLoading = useAuthStore((s) => s.setLoading)
  const resetSession = useSessionStore((s) => s.reset)
  const ownerUserId = useSessionStore((s) => s.owner_user_id)

  useEffect(() => {
    // Hydrate from current session on mount
    supabase.auth.getSession().then(({ data }) => {
      // If stored session belongs to a different user, wipe it
      if (ownerUserId && data.session?.user?.id && data.session.user.id !== ownerUserId) {
        resetSession()
      }
      setSession(data.session)
      setLoading(false)
    })

    // Subscribe to future changes (login, logout, token refresh)
    const { data: { subscription } } = supabase.auth.onAuthStateChange((event, session) => {
      setSession(session)
      setLoading(false)
      // Wipe appraisal data on sign-out to prevent cross-user leakage
      if (event === 'SIGNED_OUT') {
        resetSession()
      }
    })

    return () => subscription.unsubscribe()
  }, [setSession, setLoading, resetSession, ownerUserId])
}
