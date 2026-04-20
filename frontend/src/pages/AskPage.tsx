import { useState } from 'react'
import ReactMarkdown from 'react-markdown'
import { api, RagResponse } from '../services/api'

export default function AskPage() {
  const [question, setQuestion] = useState('')
  const [response, setResponse] = useState<RagResponse | null>(null)
  const [loading, setLoading] = useState(false)
  const [error, setError] = useState('')

  const handleAsk = async (e: React.FormEvent) => {
    e.preventDefault()
    if (!question.trim()) return
    setLoading(true)
    setError('')
    setResponse(null)
    try {
      const data = await api.ragQuery(question, 6)
      setResponse(data)
    } catch (err: unknown) {
      setError(err instanceof Error ? err.message : 'Query failed')
    } finally {
      setLoading(false)
    }
  }

  return (
    <div>
      <h1 className="text-2xl font-bold mb-1">Ask CEEP</h1>
      <p className="text-gray-500 mb-2 text-sm">
        Ask any question about the evidence in the corpus. Every answer includes verifiable citations.
      </p>
      <p className="text-xs text-amber-700 bg-amber-50 border border-amber-200 rounded p-2 mb-6">
        CEEP only answers from evidence in its corpus. If it doesn't know, it will say so.
      </p>

      <form onSubmit={handleAsk} className="flex gap-2 mb-6">
        <input
          type="text"
          value={question}
          onChange={(e) => setQuestion(e.target.value)}
          placeholder="What changed on March 9–10, 2026 for JK registration?"
          className="flex-1 border rounded p-2 text-sm"
        />
        <button
          type="submit"
          disabled={loading}
          className="bg-blue-700 text-white px-5 py-2 rounded font-medium hover:bg-blue-800 disabled:opacity-50"
        >
          {loading ? 'Thinking…' : 'Ask'}
        </button>
      </form>

      {error && <p className="text-red-600 text-sm mb-4">{error}</p>}

      {response && (
        <div className="space-y-4">
          <div className="p-4 bg-white rounded border shadow-sm">
            <p className="text-xs font-semibold text-gray-400 mb-2 uppercase tracking-wide">Answer</p>
            <div className="prose prose-sm max-w-none text-gray-800">
              <ReactMarkdown>{response.answer}</ReactMarkdown>
            </div>
          </div>

          {response.citations.length > 0 && (
            <div className="p-4 bg-gray-50 rounded border">
              <p className="text-xs font-semibold text-gray-500 mb-3 uppercase tracking-wide">
                Citations ({response.citations.length})
              </p>
              <ol className="space-y-3">
                {response.citations.map((c, i) => {
                  let hostname = ''
                  try { hostname = c.url ? new URL(c.url).hostname : '' } catch {}
                  return (
                    <li key={i} className="text-sm border-l-2 border-blue-200 pl-3">
                      <div className="flex items-baseline gap-1 flex-wrap">
                        <span className="font-semibold text-blue-700 shrink-0">[{i + 1}]</span>
                        {c.url ? (
                          <a
                            href={c.url}
                            target="_blank"
                            rel="noopener noreferrer"
                            className="text-blue-600 underline font-medium break-all"
                          >
                            {c.label && c.label !== 'Source' ? c.label : hostname || c.url}
                          </a>
                        ) : (
                          <span className="font-medium text-gray-700">{c.label || 'Source'}</span>
                        )}
                      </div>
                      {c.excerpt && (
                        <p className="text-gray-500 text-xs mt-1 italic leading-relaxed">
                          "{c.excerpt.slice(0, 250)}{c.excerpt.length > 250 ? '…' : ''}"
                        </p>
                      )}
                    </li>
                  )
                })}
              </ol>
            </div>
          )}

          <p className="text-xs text-gray-400">
            {response.input_tokens} input tokens · {response.output_tokens} output tokens ·{' '}
            {response.latency_ms} ms
          </p>
        </div>
      )}
    </div>
  )
}
