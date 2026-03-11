import React, { useCallback } from 'react'
import { useDropzone } from 'react-dropzone'
import { Upload, X, FileText, AlertCircle } from 'lucide-react'

interface FileDropzoneProps {
  onFiles: (files: File[]) => void
  files: File[]
  onRemove: (index: number) => void
  accept?: Record<string, string[]>
  maxFiles?: number
  maxSizeMB?: number
  label?: string
  hint?: string
  error?: string
}

const defaultAccept = {
  'application/pdf': ['.pdf'],
  'text/csv': ['.csv'],
  'application/json': ['.json'],
}

function formatSize(bytes: number) {
  if (bytes < 1024) return `${bytes} B`
  if (bytes < 1024 * 1024) return `${(bytes / 1024).toFixed(1)} KB`
  return `${(bytes / 1024 / 1024).toFixed(1)} MB`
}

const fileIcons: Record<string, string> = {
  'application/pdf': '📄',
  'text/csv': '📊',
  'application/json': '🗂️',
}

export default function FileDropzone({
  onFiles,
  files,
  onRemove,
  accept = defaultAccept,
  maxFiles = 10,
  maxSizeMB = 50,
  label = 'Drop files here',
  hint,
  error,
}: FileDropzoneProps) {
  const onDrop = useCallback(
    (accepted: File[]) => {
      onFiles(accepted)
    },
    [onFiles],
  )

  const { getRootProps, getInputProps, isDragActive, fileRejections } = useDropzone({
    onDrop,
    accept,
    maxFiles,
    maxSize: maxSizeMB * 1024 * 1024,
    multiple: true,
  })

  const rejectionMessages = fileRejections
    .flatMap((r) => r.errors.map((e) => e.message))
    .filter((v, i, a) => a.indexOf(v) === i)
    .slice(0, 3)

  return (
    <div className="space-y-3">
      <div
        {...getRootProps()}
        className={[
          'border-2 border-dashed rounded-xl px-6 py-8 text-center cursor-pointer transition-all duration-150',
          isDragActive
            ? 'border-primary bg-primary/8 scale-[1.01]'
            : 'border-border-dark hover:border-primary/50 hover:bg-surface2/60',
        ].join(' ')}
      >
        <input {...getInputProps()} />
        <div className="flex flex-col items-center gap-2">
          <div className={[
            'w-12 h-12 rounded-full flex items-center justify-center transition-colors',
            isDragActive ? 'bg-primary/20' : 'bg-surface2',
          ].join(' ')}>
            <Upload size={22} className={isDragActive ? 'text-primary' : 'text-text-muted'} />
          </div>
          <div>
            <p className="text-text-primary text-sm font-medium">
              {isDragActive ? 'Release to upload' : label}
            </p>
            <p className="text-text-muted text-xs mt-1">
              {hint || `or click to browse · max ${maxSizeMB}MB per file`}
            </p>
            <p className="text-text-muted text-xs mt-0.5">
              Accepted: {Object.values(accept).flat().join(', ')}
            </p>
          </div>
        </div>
      </div>

      {/* Rejection errors */}
      {rejectionMessages.length > 0 && (
        <div className="flex items-start gap-2 text-danger bg-danger/8 border border-danger/25 rounded-lg px-3 py-2">
          <AlertCircle size={14} className="flex-shrink-0 mt-0.5" />
          <div className="text-xs space-y-0.5">
            {rejectionMessages.map((msg, i) => <p key={i}>{msg}</p>)}
          </div>
        </div>
      )}

      {/* Error */}
      {error && (
        <div className="flex items-center gap-2 text-danger text-xs">
          <AlertCircle size={13} />
          {error}
        </div>
      )}

      {/* File list */}
      {files.length > 0 && (
        <ul className="space-y-1.5">
          {files.map((file, i) => (
            <li
              key={`${file.name}-${i}`}
              className="flex items-center justify-between gap-3 bg-surface2 border border-border-dark rounded-lg px-3 py-2"
            >
              <div className="flex items-center gap-2 min-w-0">
                <span className="text-base flex-shrink-0">{fileIcons[file.type] || '📁'}</span>
                <div className="min-w-0">
                  <p className="text-xs text-text-primary font-medium truncate">{file.name}</p>
                  <p className="text-xs text-text-muted">{formatSize(file.size)}</p>
                </div>
              </div>
              <button
                onClick={(e) => { e.stopPropagation(); onRemove(i) }}
                className="text-text-muted hover:text-danger transition-colors flex-shrink-0"
              >
                <X size={14} />
              </button>
            </li>
          ))}
        </ul>
      )}
    </div>
  )
}
