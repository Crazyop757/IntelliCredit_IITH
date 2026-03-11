import React, { lazy, Suspense } from 'react'
import { BrowserRouter, Routes, Route } from 'react-router-dom'
import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import { Toaster } from 'react-hot-toast'
import AppLayout from './components/layout/AppLayout'
import ErrorBoundary from './components/ErrorBoundary'
import Skeleton from './components/ui/Skeleton'

const LandingPage = lazy(() => import('./pages/LandingPage'))
const Dashboard = lazy(() => import('./pages/Dashboard'))
const AppraisalPage = lazy(() => import('./pages/AppraisalPage'))
const CompaniesPage = lazy(() => import('./pages/CompaniesPage'))
const CompanyDetail = lazy(() => import('./pages/CompanyDetail'))
const NotFound = lazy(() => import('./pages/NotFound'))

const queryClient = new QueryClient({
  defaultOptions: {
    queries: {
      retry: 1,
      staleTime: 30_000,
      refetchOnWindowFocus: false,
    },
  },
})

function PageLoader() {
  return (
    <div className="space-y-4 p-2">
      <Skeleton className="h-10 w-64 rounded-xl" />
      <div className="grid grid-cols-4 gap-4">
        {Array.from({ length: 4 }).map((_, i) => (
          <Skeleton key={i} className="h-28 rounded-xl" />
        ))}
      </div>
      <Skeleton className="h-64 rounded-xl" />
    </div>
  )
}

export default function App() {
  return (
    <QueryClientProvider client={queryClient}>
      <BrowserRouter>
        <ErrorBoundary>
          <Routes>
            {/* Standalone landing page - no app shell */}
            <Route
              path="/"
              element={
                <Suspense fallback={<div className="min-h-screen bg-[#080C14]" />}>
                  <LandingPage />
                </Suspense>
              }
            />
            {/* App routes wrapped in sidebar/topbar layout */}
            <Route element={<AppLayout />}>
              <Route
                path="/dashboard"
                element={
                  <Suspense fallback={<PageLoader />}>
                    <Dashboard />
                  </Suspense>
                }
              />
              <Route
                path="/new"
                element={
                  <Suspense fallback={<PageLoader />}>
                    <AppraisalPage />
                  </Suspense>
                }
              />
              <Route
                path="/companies"
                element={
                  <Suspense fallback={<PageLoader />}>
                    <CompaniesPage />
                  </Suspense>
                }
              />
              <Route
                path="/companies/:id"
                element={
                  <Suspense fallback={<PageLoader />}>
                    <CompanyDetail />
                  </Suspense>
                }
              />
            </Route>
            <Route
              path="*"
              element={
                <Suspense fallback={<PageLoader />}>
                  <NotFound />
                </Suspense>
              }
            />
          </Routes>
        </ErrorBoundary>

        <Toaster
          position="top-right"
          gutter={8}
          toastOptions={{
            duration: 4000,
            style: {
              background: '#1E293B',
              color: '#F1F5F9',
              border: '1px solid #334155',
              borderRadius: '12px',
              fontSize: '13px',
              maxWidth: '400px',
              boxShadow: '0 4px 24px rgba(0,0,0,0.4)',
            },
            success: {
              iconTheme: { primary: '#22C55E', secondary: '#1E293B' },
            },
            error: {
              iconTheme: { primary: '#EF4444', secondary: '#1E293B' },
            },
          }}
        />
      </BrowserRouter>
    </QueryClientProvider>
  )
}
