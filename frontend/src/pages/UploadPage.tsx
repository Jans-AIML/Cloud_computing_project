import { useState, useRef } from 'react'
import { api } from '../services/api'

type SourceType = 'pdf' | 'email' | 'url'

export default function UploadPage() {
  const [sourceType, setSourceType] = useState<SourceType>('pdf')
  const [file, setFile] = useState<File | null>(null)
  const [sourceUrl, setSourceUrl] = useState('')
  const [consent, setConsent] = useState(false)
  const [status, setStatus] = useState<'idle' | 'uploading' | 'processing' | 'done' | 'error'>('idle')
  const [message, setMessage] = useState('')
  const fileRef = useRef<HTMLInputElement>(null)

  const handleUpload = async () => {
    if (sourceType !== 'url' && !file) {
      setMessage('Please select a file.')
      return
    }
    if (sourceType === 'url' && !sourceUrl.trim()) {
      setMessage('Please enter a URL.')
      return
    }
    if (sourceType === 'email' && !consent) {
      setMessage('You must consent to PII redaction before submitting an email.')
      return
    }

    setStatus('uploading')
    setMessage('')

    try {
      const uploadReq = {
        filename: file?.name ?? 'page.html',
        content_type: file?.type ?? 'text/html',
        source_type: sourceType,
        source_url: sourceUrl || undefined,
        consent_given: consent,
      }

      const { document_id, upload_url } = await api.requestUpload(uploadReq)

      if (file) {
        await api.uploadFileToS3(upload_url, file)
      }

      // For PDF and email sources, trigger in-process ETL now that the file is in S3
      if (sourceType === 'pdf' || sourceType === 'email') {
        setStatus('processing')
        setMessage('Processing document…')
        await api.processDocument(document_id)
      }

      setStatus('done')
      setMessage('Document submitted and processed! It is now searchable in the corpus.')
      setFile(null)
      if (fileRef.current) fileRef.current.value = ''
    } catch (err: unknown) {
      setStatus('error')
      setMessage(err instanceof Error ? err.message : 'Upload failed.')
    }
  }

  return (
    <div>
      <h1 className="text-2xl font-bold mb-1">Add Evidence</h1>
      <p className="text-gray-500 mb-6 text-sm">
        Submit public documents, PDFs, or community emails to the evidence corpus.
      </p>

      {/* Source type selector */}
      <div className="flex gap-3 mb-6">
        {(['pdf', 'email', 'url'] as SourceType[]).map((t) => (
          <button
            key={t}
            onClick={() => { setSourceType(t); setConsent(false) }}
            className={`px-4 py-2 rounded border font-medium capitalize transition-colors ${
              sourceType === t ? 'bg-blue-700 text-white border-blue-700' : 'bg-white border-gray-300 hover:border-blue-400'
            }`}
          >
            {t === 'pdf' ? 'PDF / Document' : t === 'email' ? 'Community Email' : 'Web URL'}
          </button>
        ))}
      </div>

      {/* File picker */}
      {sourceType !== 'url' && (
        <div className="mb-4">
          <label className="block text-sm font-medium mb-1">
            {sourceType === 'email' ? 'Email file (.eml or .txt)' : 'PDF file'}
          </label>
          <input
            ref={fileRef}
            type="file"
            accept={sourceType === 'email' ? '.eml,.txt' : '.pdf'}
            onChange={(e) => setFile(e.target.files?.[0] ?? null)}
            className="block w-full text-sm border rounded p-2"
          />
        </div>
      )}

      {/* URL input */}
      {sourceType === 'url' && (
        <div className="mb-4">
          <label className="block text-sm font-medium mb-1">Web page URL</label>
          <input
            type="url"
            value={sourceUrl}
            onChange={(e) => setSourceUrl(e.target.value)}
            placeholder="https://..."
            className="w-full border rounded p-2 text-sm"
          />
        </div>
      )}

      {/* Consent modal for emails */}
      {sourceType === 'email' && (
        <div className="mb-4 p-4 bg-amber-50 border border-amber-300 rounded text-sm">
          <p className="font-semibold text-amber-800 mb-2">Privacy & Consent Notice</p>
          <p className="text-amber-700 mb-3">
            CEEP will store a <strong>PII-redacted excerpt</strong> of this email as an evidence card.
            Your name, email address, phone number, and home address will be automatically removed
            before anything is saved or displayed. The original email is stored encrypted and is
            never shown to anyone. You can request deletion at any time.
          </p>
          <label className="flex items-center gap-2 cursor-pointer">
            <input
              type="checkbox"
              checked={consent}
              onChange={(e) => setConsent(e.target.checked)}
              className="h-4 w-4"
            />
            <span className="font-medium">I consent to the processing described above</span>
          </label>
        </div>
      )}

      <button
        onClick={handleUpload}
        disabled={status === 'uploading'}
        className="bg-blue-700 text-white px-6 py-2 rounded font-medium hover:bg-blue-800 disabled:opacity-50 transition-colors"
      >
        {status === 'uploading' ? 'Uploading…' : status === 'processing' ? 'Processing…' : 'Submit'}
      </button>

      {message && (
        <p className={`mt-4 text-sm p-3 rounded ${
          status === 'error' ? 'bg-red-50 text-red-700' : 'bg-green-50 text-green-700'
        }`}>
          {message}
        </p>
      )}
    </div>
  )
}
