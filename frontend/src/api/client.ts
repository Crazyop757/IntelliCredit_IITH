import axios, { type AxiosError } from 'axios'
import toast from 'react-hot-toast'
import { useAuthStore } from '../store/authStore'

const BASE_URL = (import.meta.env.VITE_API_URL as string) || 'http://localhost:8000/api/v1'
const API_KEY = (import.meta.env.VITE_API_KEY as string) || 'dev-key-change-in-production'

const client = axios.create({
  baseURL: BASE_URL,
  timeout: 120_000,
  headers: {
    'Content-Type': 'application/json',
  },
})

// ─── Request interceptor ──────────────────────────────────────────────────────

client.interceptors.request.use((config) => {
  config.headers['X-API-Key'] = API_KEY
  config.headers['X-Request-ID'] = crypto.randomUUID()
  // Attach Supabase JWT if the user is authenticated
  const session = useAuthStore.getState().session
  if (session?.access_token) {
    config.headers['Authorization'] = `Bearer ${session.access_token}`
  }
  return config
})

// ─── Response interceptor ─────────────────────────────────────────────────────

client.interceptors.response.use(
  (response) => {
    // Unwrap envelope {success, data} if present (FastAPI doesn't always use this)
    if (
      response.data &&
      typeof response.data === 'object' &&
      'success' in response.data &&
      'data' in response.data
    ) {
      return { ...response, data: response.data.data }
    }
    return response
  },
  async (error: AxiosError<{ detail?: string | Array<{ loc: string[]; msg: string }> }>) => {
    if (!error.response) {
      toast.error('Cannot connect to server — check that the API is running', {
        id: 'network-error',
        duration: 5000,
      })
    } else if (error.response.status >= 500) {
      toast.error(`Server error (${error.response.status}) — please try again`, {
        id: 'server-error',
      })
    } else if (error.response.status === 422) {
      const detail = error.response.data?.detail
      if (Array.isArray(detail)) {
        const msg = detail
          .map((e) => `${e.loc?.slice(1).join('.')} — ${e.msg}`)
          .join('; ')
        toast.error(msg, { duration: 6000 })
      } else if (typeof detail === 'string') {
        toast.error(detail)
      }
    } else if (error.response.status === 401) {
      // Clear auth state and redirect to login
      useAuthStore.getState().clearAuth()
      toast.error('Session expired — please sign in again', { id: 'auth-error' })
      window.location.href = '/auth/login'
    } else if (error.response.status === 403) {
      toast.error('Access denied', { id: 'auth-error' })
    } else if (error.response.status === 429) {
      const retryAfter = Number(error.response.headers['retry-after']) || 5
      toast.error(`Rate limited — retrying in ${retryAfter}s`, { id: 'rate-limit' })
      await new Promise((resolve) => setTimeout(resolve, retryAfter * 1000))
      return client.request(error.config!)
    }
    return Promise.reject(error)
  }
)

// ─── Typed helpers ─────────────────────────────────────────────────────────────

export async function get<T>(url: string, params?: Record<string, unknown>): Promise<T> {
  const res = await client.get<T>(url, { params })
  return res.data
}

export async function post<T>(url: string, data?: unknown): Promise<T> {
  const res = await client.post<T>(url, data)
  return res.data
}

export async function postForm<T>(url: string, formData: FormData): Promise<T> {
  const res = await client.post<T>(url, formData, {
    headers: { 'Content-Type': 'multipart/form-data' },
  })
  return res.data
}

export async function downloadFile(url: string, filename?: string): Promise<void> {
  const res = await client.get<Blob>(url, { responseType: 'blob' })
  const blob = new Blob([res.data])
  const link = document.createElement('a')
  link.href = URL.createObjectURL(blob)

  const contentDisposition = res.headers['content-disposition'] as string | undefined
  const serverFilename = contentDisposition
    ?.split('filename=')[1]
    ?.replace(/['"]/g, '')
    ?.trim()

  link.download = filename ?? serverFilename ?? 'credit_appraisal.pdf'
  document.body.appendChild(link)
  link.click()
  document.body.removeChild(link)
  URL.revokeObjectURL(link.href)
}

export { client as apiClient }
export default client
