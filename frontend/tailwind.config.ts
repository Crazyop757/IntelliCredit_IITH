import type { Config } from 'tailwindcss'

export default {
  content: ['./index.html', './src/**/*.{js,ts,jsx,tsx}'],
  theme: {
    extend: {
      colors: {
        // Dark theme palette (matches LandingPage)
        navy: '#080C14',
        'app-bg': '#080C14',
        surface: '#0D1117',
        surface2: '#111827',
        'surface-hover': '#1A1F2E',
        'border-dark': '#1E293B',
        'border-strong': '#334155',
        primary: '#2563EB',
        'primary-hover': '#1D4ED8',
        'primary-light': 'rgba(37,99,235,0.12)',
        accent: '#00FF94',
        gold: '#F59E0B',
        success: '#22C55E',
        danger: '#EF4444',
        'text-primary': '#FFFFFF',
        'text-secondary': '#94A3B8',
        'text-muted': '#64748B',
        sidebar: '#0D1117',
      },
      fontFamily: {
        sans: ['Inter', 'ui-sans-serif', 'system-ui', 'sans-serif'],
        mono: ['JetBrains Mono', 'ui-monospace', 'monospace'],
      },
      animation: {
        'pulse-slow': 'pulse 2s ease-in-out infinite',
        'spin-slow': 'spin 3s linear infinite',
        'fade-in': 'fadeIn 0.2s ease-out',
        'slide-up': 'slideUp 0.2s ease-out',
      },
      keyframes: {
        fadeIn: {
          '0%': { opacity: '0' },
          '100%': { opacity: '1' },
        },
        slideUp: {
          '0%': { opacity: '0', transform: 'translateY(8px)' },
          '100%': { opacity: '1', transform: 'translateY(0)' },
        },
      },
      boxShadow: {
        card: '0 1px 3px rgba(0,0,0,0.3), 0 4px 16px rgba(0,0,0,0.2)',
        'card-hover': '0 4px 24px rgba(0,0,0,0.4)',
        glow: '0 0 24px rgba(37,99,235,0.25)',
        navbar: '0 1px 0 #1E293B',
        'hero-card': '0 8px 40px rgba(0,0,0,0.4)',
      },
      backgroundImage: {
        'gradient-hero': 'linear-gradient(135deg, #080C14 0%, #0D1117 60%, #111827 100%)',
        'gradient-hero-dark': 'linear-gradient(135deg, #080C14 0%, #0D1117 100%)',
        'gradient-primary': 'linear-gradient(135deg, #2563EB 0%, #1D4ED8 100%)',
        'gradient-success': 'linear-gradient(135deg, #22C55E 0%, #16A34A 100%)',
        'gradient-danger': 'linear-gradient(135deg, #EF4444 0%, #DC2626 100%)',
        'gradient-gold': 'linear-gradient(135deg, #F59E0B 0%, #D97706 100%)',
        'gradient-card': 'linear-gradient(135deg, #0D1117 0%, #111827 100%)',
      },
    },
  },
  plugins: [],
} satisfies Config
