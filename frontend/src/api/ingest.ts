import { postForm } from './client'
import type { IngestResult } from '../store/types'

export const uploadFiles = (formData: FormData): Promise<IngestResult> =>
  postForm<IngestResult>('/ingest/full', formData)

export const uploadPDF = (formData: FormData): Promise<IngestResult> =>
  postForm<IngestResult>('/ingest/pdf', formData)

export const uploadBank = (formData: FormData): Promise<IngestResult> =>
  postForm<IngestResult>('/ingest/bank', formData)

export const uploadGST = (formData: FormData): Promise<IngestResult> =>
  postForm<IngestResult>('/ingest/gst', formData)
