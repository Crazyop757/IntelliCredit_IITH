import React, { createContext, useContext } from 'react'

interface TabsContextValue {
  activeTab: string
  setActiveTab: (id: string) => void
}

const TabsContext = createContext<TabsContextValue>({ activeTab: '', setActiveTab: () => {} })

interface TabsProps {
  value: string
  onChange: (value: string) => void
  children: React.ReactNode
  className?: string
}

export function Tabs({ value, onChange, children, className = '' }: TabsProps) {
  return (
    <TabsContext.Provider value={{ activeTab: value, setActiveTab: onChange }}>
      <div className={className}>{children}</div>
    </TabsContext.Provider>
  )
}

interface TabListProps {
  children: React.ReactNode
  className?: string
}

export function TabList({ children, className = '' }: TabListProps) {
  return (
    <div className={['overflow-x-auto', className].join(' ')}>
      <div
        className="flex items-center gap-1 border-b border-border-dark min-w-max"
        role="tablist"
      >
        {children}
      </div>
    </div>
  )
}

interface TabTriggerProps {
  value: string
  children: React.ReactNode
  icon?: React.ReactNode
  disabled?: boolean
}

export function TabTrigger({ value, children, icon, disabled = false }: TabTriggerProps) {
  const { activeTab, setActiveTab } = useContext(TabsContext)
  const isActive = activeTab === value

  return (
    <button
      role="tab"
      aria-selected={isActive}
      disabled={disabled}
      onClick={() => !disabled && setActiveTab(value)}
      className={[
        'flex items-center gap-2 px-4 py-3 text-sm font-medium transition-all duration-150',
        'border-b-2 -mb-px whitespace-nowrap',
        isActive
          ? 'text-primary border-primary'
          : 'text-text-secondary border-transparent hover:text-text-primary hover:border-border-dark',
        disabled ? 'opacity-40 cursor-not-allowed' : 'cursor-pointer',
      ].join(' ')}
    >
      {icon && <span className="opacity-80">{icon}</span>}
      {children}
    </button>
  )
}

interface TabContentProps {
  value: string
  children: React.ReactNode
  className?: string
}

export function TabContent({ value, children, className = '' }: TabContentProps) {
  const { activeTab } = useContext(TabsContext)
  if (activeTab !== value) return null
  return (
    <div role="tabpanel" className={className}>
      {children}
    </div>
  )
}

export default Tabs
