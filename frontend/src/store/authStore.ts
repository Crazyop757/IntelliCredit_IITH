import { create } from 'zustand'
import { persist } from 'zustand/middleware'
import type { Session, User } from '@supabase/supabase-js'

interface AuthState {
  session: Session | null
  user: User | null
  isLoading: boolean
  setSession: (session: Session | null) => void
  setUser: (user: User | null) => void
  setLoading: (v: boolean) => void
  clearAuth: () => void
}

export const useAuthStore = create<AuthState>()(
  persist(
    (set) => ({
      session: null,
      user: null,
      isLoading: true,

      setSession: (session) => set({ session, user: session?.user ?? null }),
      setUser: (user) => set({ user }),
      setLoading: (v) => set({ isLoading: v }),
      clearAuth: () => set({ session: null, user: null, isLoading: false }),
    }),
    {
      name: 'finsight_auth',
      partialize: (state) => ({
        session: state.session,
        user: state.user,
      }),
    }
  )
)
