import { create } from 'zustand'
import type { UIState } from './types'

export const useUIStore = create<UIState>()((set) => ({
  sidebarCollapsed: false,
  apiOnline: null,
  setSidebarCollapsed: (v: boolean) => set({ sidebarCollapsed: v }),
  setApiOnline: (v: boolean) => set({ apiOnline: v }),
}))
