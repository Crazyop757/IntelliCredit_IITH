import React from 'react'
import { Outlet, useLocation } from 'react-router-dom'
import { motion, AnimatePresence } from 'framer-motion'
import Sidebar from './Sidebar'
import TopBar from './TopBar'
import { HealthBanner } from '../shared/HealthBanner'
import { useUIStore } from '../../store/uiStore'

const pageVariants = {
  initial: { opacity: 0, y: 10 },
  animate: { opacity: 1, y: 0 },
  exit: { opacity: 0, y: -6 },
}

export default function AppLayout() {
  const collapsed = useUIStore((s) => s.sidebarCollapsed)
  const location = useLocation()

  return (
    <div className="flex bg-app-bg min-h-screen">
      <Sidebar />
      <div
        className={[
          'flex-1 flex flex-col min-h-screen transition-all duration-200',
          collapsed ? 'ml-16' : 'ml-64',
        ].join(' ')}
      >
        <HealthBanner />
        <TopBar />
        <main className="flex-1 p-6 max-w-screen-2xl">
          <AnimatePresence mode="wait">
            <motion.div
              key={location.pathname}
              variants={pageVariants}
              initial="initial"
              animate="animate"
              exit="exit"
              transition={{ duration: 0.18, ease: 'easeOut' }}
            >
              <Outlet />
            </motion.div>
          </AnimatePresence>
        </main>
      </div>
    </div>
  )
}
