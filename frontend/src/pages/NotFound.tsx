import React from 'react'
import { Link } from 'react-router-dom'
import { motion } from 'framer-motion'
import { Home, ArrowLeft } from 'lucide-react'

export default function NotFound() {
  return (
    <div className="min-h-screen bg-navy flex items-center justify-center px-6">
      <motion.div
        initial={{ opacity: 0, y: 20 }}
        animate={{ opacity: 1, y: 0 }}
        transition={{ duration: 0.4 }}
        className="text-center max-w-md"
      >
        <motion.p
          className="text-[7rem] font-black leading-none text-primary/20 select-none"
          initial={{ scale: 0.8 }}
          animate={{ scale: 1 }}
          transition={{ delay: 0.1, type: 'spring', stiffness: 120 }}
        >
          404
        </motion.p>
        <h1 className="text-text-primary text-2xl font-bold mt-2 mb-2">Page not found</h1>
        <p className="text-text-secondary text-sm mb-8">
          The page you're looking for doesn't exist or has been moved.
        </p>
        <div className="flex gap-3 justify-center">
          <Link
            to="/"
            className="flex items-center gap-2 px-4 py-2 bg-primary hover:bg-primary/90 transition-colors text-white text-sm font-medium rounded-lg"
          >
            <Home size={14} /> Go to Dashboard
          </Link>
          <button
            onClick={() => window.history.back()}
            className="flex items-center gap-2 px-4 py-2 border border-border-dark text-text-secondary hover:text-text-primary hover:border-primary/40 transition-colors text-sm font-medium rounded-lg"
          >
            <ArrowLeft size={14} /> Go Back
          </button>
        </div>
      </motion.div>
    </div>
  )
}
