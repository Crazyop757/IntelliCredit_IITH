import React from 'react'

interface CardProps {
  children: React.ReactNode
  className?: string
  elevated?: boolean
  onClick?: () => void
  hover?: boolean
  style?: React.CSSProperties
}

export default function Card({ children, className = '', elevated = false, onClick, hover = false, style }: CardProps) {
  const base = elevated
    ? 'bg-surface2 border border-border-dark'
    : 'bg-surface border border-border-dark'

  const hoverClass = hover || onClick ? 'cursor-pointer hover:shadow-card-hover hover:border-primary/30 transition-all duration-200' : ''

  return (
    <div
      className={`rounded-xl shadow-card ${base} ${hoverClass} ${className}`}
      onClick={onClick}
      style={style}
    >
      {children}
    </div>
  )
}

interface CardHeaderProps {
  children: React.ReactNode
  className?: string
  action?: React.ReactNode
}

export function CardHeader({ children, className = '', action }: CardHeaderProps) {
  return (
    <div className={`flex items-center justify-between px-5 py-4 border-b border-border-dark ${className}`}>
      <div className="flex items-center gap-3">{children}</div>
      {action && <div className="flex items-center gap-2">{action}</div>}
    </div>
  )
}

interface CardTitleProps {
  children: React.ReactNode
  className?: string
  icon?: React.ReactNode
  description?: string
}

export function CardTitle({ children, className = '', icon, description }: CardTitleProps) {
  return (
    <div className={className}>
      <div className="flex items-center gap-2">
        {icon && <span className="text-text-secondary">{icon}</span>}
        <h3 className="font-semibold text-text-primary text-base leading-none">{children}</h3>
      </div>
      {description && <p className="text-text-muted text-xs mt-1">{description}</p>}
    </div>
  )
}

interface CardBodyProps {
  children: React.ReactNode
  className?: string
}

export function CardBody({ children, className = '' }: CardBodyProps) {
  return <div className={`p-5 ${className}`}>{children}</div>
}
