import { useState } from 'react'
import { api, SearchResult } from '../services/api'

const SOURCE_BADGE: Record<string, { label: string; cls: string }> = {
  pdf:   { label: 'PDF',   cls: 'bg-orange-100 text-orange-700' },
  url:   { label: 'Web',   cls: 'bg-green-100  text-green-700'  },
  email: { label: 'Email', cls: 'bg-purple-100 text-purple-700' },
}

function SourceBadge({ type }: { type: string | null }) {
  const badge = SOURCE_BADGE[type ?? ''] ?? { label: type ?? 'Doc', cls: 'bg-gray-100 text-gray-600' }
  return (
    <span className={`text-xs font-semibold px-2 py-0.5 rounded ${badge.cls}`}>
      {badge.label}
    </span>
  )
}

function ResultCard({ r }: { r: SearchResult }) {
  const [expanded, setExpanded] = useState(false)
  const MAX = 400
  const long = r.chunk_text.length > MAX
  const displayed = expanded || !long ? r.chunk_text : r.chunk_text.slice(0, MAX) + '…'

  // Derive a display label: use citation_label if set, fall back to URL hostname
  let sourceLabel = r.citation_label
  if (!sourceLabel && r.citation_url) {
    try { sourceLabel = new URL(r.citation_url).hostname } catch { /* ignore */ }
  }

  return (
    <div className="p-4 bg-white rounded border shadow-sm">
      {/* Header row */}
      <div className="flex items-center gap-2 mb-2 flex-wrap">
        <SourceBadge type={r.source_type} />
        {sourceLabel && (
          r.citation_url
            ? <a href={r.citation_url} target="_blank" rel="noopener noreferrer"
                className="text-sm font-medium text-blue-700 hover:underline truncate max-w-xs">
                {sourceLabel}
              </a>
            : <span className="text-sm font-medium text-gray-700 truncate max-w-xs">{sourceLabel}</span>
        )}
        <span className="ml-auto text-xs text-gray-400 shrink-0">
          {(r.score * 100).toFixed(0)}% match
        </span>
      </div>

      {/* Chunk text */}
      <p className="text-sm text-gray-800 whitespace-pre-line leading-relaxed">{displayed}</p>
      {long && (
        <button
          onClick={() => setExpanded(!expanded)}
          className="text-xs text-blue-600 hover:underline mt-1"
        >
          {expanded ? 'Show less' : 'Show more'}
        </button>
      )}

      {/* Topic tags */}
      {r.topic_tags.length > 0 && (
        <div className="mt-2 flex gap-1 flex-wrap">
          {r.topic_tags.map((t) => (
            <span key={t} className="text-xs bg-gray-100 text-gray-500 px-2 py-0.5 rounded">
              {t}
            </span>
          ))}
        </div>
      )}
    </div>
  )
}

export default function SearchPage() {
  const [query, setQuery] = useState('')
  const [results, setResults] = useState<SearchResult[]>([])
  const [loading, setLoading] = useState(false)
  const [error, setError] = useState('')

  const handleSearch = async (e: React.FormEvent) => {
    e.preventDefault()
    if (!query.trim()) return
    setLoading(true)
    setError('')
    try {
      const data = await api.search(query, 8)
      setResults(data)
    } catch (err: unknown) {
      setError(err instanceof Error ? err.message : 'Search failed')
    } finally {
      setLoading(false)
    }
  }

  return (
    <div>
      <h1 className="text-2xl font-bold mb-1">Search Evidence</h1>
      <p className="text-gray-500 mb-6 text-sm">
        Keyword and vector search across all evidence cards in the corpus.
      </p>

      <form onSubmit={handleSearch} className="flex gap-2 mb-6">
        <input
          type="search"
          value={query}
          onChange={(e) => setQuery(e.target.value)}
          placeholder="e.g. JK registration, capacity, Lady Evelyn…"
          className="flex-1 border rounded p-2 text-sm"
        />
        <button
          type="submit"
          disabled={loading}
          className="bg-blue-700 text-white px-5 py-2 rounded font-medium hover:bg-blue-800 disabled:opacity-50"
        >
          {loading ? 'Searching…' : 'Search'}
        </button>
      </form>

      {error && <p className="text-red-600 text-sm mb-4">{error}</p>}

      {results.length > 0 && (
        <p className="text-xs text-gray-400 mb-3">
          {results.length} result{results.length !== 1 ? 's' : ''} — sorted by relevance
        </p>
      )}

      {results.length === 0 && !loading && query && (
        <p className="text-gray-500 text-sm">No results found. Try different keywords or add more documents.</p>
      )}

      <div className="space-y-4">
        {results.map((r) => <ResultCard key={r.chunk_id} r={r} />)}
      </div>
    </div>
  )
}

