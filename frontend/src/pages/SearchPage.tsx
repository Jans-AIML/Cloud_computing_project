import { useState } from 'react'
import { api, SearchResult } from '../services/api'

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

      {results.length === 0 && !loading && query && (
        <p className="text-gray-500 text-sm">No results found. Try different keywords or add more documents.</p>
      )}

      <div className="space-y-4">
        {results.map((r) => (
          <div key={r.chunk_id} className="p-4 bg-white rounded border shadow-sm">
            <div className="flex items-start justify-between gap-2 mb-2">
              <span className="text-xs font-semibold text-blue-700 bg-blue-50 px-2 py-0.5 rounded">
                Score: {(r.score * 100).toFixed(1)}%
              </span>
              {r.citation_label && (
                <span className="text-xs text-gray-500">{r.citation_label}</span>
              )}
            </div>
            <p className="text-sm text-gray-800 whitespace-pre-line">{r.chunk_text}</p>
            {r.citation_url && (
              <a
                href={r.citation_url}
                target="_blank"
                rel="noopener noreferrer"
                className="text-xs text-blue-600 underline mt-2 inline-block"
              >
                Source ↗
              </a>
            )}
            {r.topic_tags.length > 0 && (
              <div className="mt-2 flex gap-1 flex-wrap">
                {r.topic_tags.map((t) => (
                  <span key={t} className="text-xs bg-gray-100 text-gray-600 px-2 py-0.5 rounded">
                    {t}
                  </span>
                ))}
              </div>
            )}
          </div>
        ))}
      </div>
    </div>
  )
}
