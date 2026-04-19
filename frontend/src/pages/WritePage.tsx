import { useState, useEffect } from 'react'
import ReactMarkdown from 'react-markdown'
import { api, BriefTemplate, BriefResponse } from '../services/api'

export default function WritePage() {
  const [templates, setTemplates] = useState<BriefTemplate[]>([])
  const [templateId, setTemplateId] = useState('')
  const [goal, setGoal] = useState('')
  const [audience, setAudience] = useState('')
  const [tone, setTone] = useState<'formal' | 'community'>('formal')
  const [extraContext, setExtraContext] = useState('')
  const [result, setResult] = useState<BriefResponse | null>(null)
  const [loading, setLoading] = useState(false)
  const [error, setError] = useState('')

  useEffect(() => {
    api.listTemplates().then((data) => {
      setTemplates(data)
      if (data.length > 0) setTemplateId(data[0].id)
    })
  }, [])

  const handleGenerate = async (e: React.FormEvent) => {
    e.preventDefault()
    if (!templateId || !goal.trim() || !audience.trim()) return
    setLoading(true)
    setError('')
    setResult(null)
    try {
      const data = await api.generateBrief({ template_id: templateId, goal, audience, tone, extra_context: extraContext })
      setResult(data)
    } catch (err: unknown) {
      setError(err instanceof Error ? err.message : 'Generation failed')
    } finally {
      setLoading(false)
    }
  }

  const selectedTemplate = templates.find((t) => t.id === templateId)

  return (
    <div>
      <h1 className="text-2xl font-bold mb-1">Write a Brief or Letter</h1>
      <p className="text-gray-500 mb-6 text-sm">
        Generate an evidence-backed draft. Always review and edit before sending.
      </p>

      <form onSubmit={handleGenerate} className="space-y-4 mb-6">
        <div>
          <label className="block text-sm font-medium mb-1">Template</label>
          <select
            value={templateId}
            onChange={(e) => setTemplateId(e.target.value)}
            className="w-full border rounded p-2 text-sm"
          >
            {templates.map((t) => (
              <option key={t.id} value={t.id}>{t.name}</option>
            ))}
          </select>
          {selectedTemplate && (
            <p className="text-xs text-gray-500 mt-1">
              {selectedTemplate.description} · {selectedTemplate.typical_length}
            </p>
          )}
        </div>

        <div>
          <label className="block text-sm font-medium mb-1">Your goal</label>
          <input
            type="text"
            value={goal}
            onChange={(e) => setGoal(e.target.value)}
            placeholder="e.g. Request restoration of full JK programming at Lady Evelyn"
            className="w-full border rounded p-2 text-sm"
            required
          />
        </div>

        <div>
          <label className="block text-sm font-medium mb-1">Audience</label>
          <input
            type="text"
            value={audience}
            onChange={(e) => setAudience(e.target.value)}
            placeholder="e.g. OCDSB Supervisor of Education"
            className="w-full border rounded p-2 text-sm"
            required
          />
        </div>

        <div>
          <label className="block text-sm font-medium mb-1">Tone</label>
          <div className="flex gap-4">
            {(['formal', 'community'] as const).map((t) => (
              <label key={t} className="flex items-center gap-2 cursor-pointer text-sm capitalize">
                <input type="radio" value={t} checked={tone === t} onChange={() => setTone(t)} />
                {t}
              </label>
            ))}
          </div>
        </div>

        <div>
          <label className="block text-sm font-medium mb-1">Additional context (optional)</label>
          <textarea
            value={extraContext}
            onChange={(e) => setExtraContext(e.target.value)}
            placeholder="Any specific points you want to emphasise…"
            rows={3}
            className="w-full border rounded p-2 text-sm"
          />
        </div>

        <button
          type="submit"
          disabled={loading}
          className="bg-blue-700 text-white px-6 py-2 rounded font-medium hover:bg-blue-800 disabled:opacity-50"
        >
          {loading ? 'Generating…' : 'Generate Draft'}
        </button>
      </form>

      {error && <p className="text-red-600 text-sm mb-4">{error}</p>}

      {result && (
        <div className="space-y-4">
          <div className="p-4 bg-white rounded border shadow-sm">
            <div className="flex justify-between items-center mb-3">
              <p className="text-xs font-semibold text-gray-400 uppercase tracking-wide">Draft</p>
              <button
                onClick={() => navigator.clipboard.writeText(result.draft)}
                className="text-xs text-blue-600 hover:underline"
              >
                Copy to clipboard
              </button>
            </div>
            <div className="prose prose-sm max-w-none text-gray-800">
              <ReactMarkdown>{result.draft}</ReactMarkdown>
            </div>
          </div>

          {result.footnotes.length > 0 && (
            <div className="p-4 bg-gray-50 rounded border">
              <p className="text-xs font-semibold text-gray-500 mb-2 uppercase tracking-wide">
                Evidence Footnotes
              </p>
              <ol className="space-y-1">
                {result.footnotes.map((f, i) => (
                  <li key={i} className="text-xs text-gray-600">
                    [{i + 1}] {f.label}{' '}
                    {f.url && <a href={f.url} target="_blank" rel="noopener noreferrer" className="text-blue-600 underline">↗</a>}
                  </li>
                ))}
              </ol>
            </div>
          )}

          <p className="text-xs text-amber-700 bg-amber-50 border border-amber-200 rounded p-2">
            Review this draft carefully. CEEP assists — it does not replace your judgment. Remove or
            correct anything that is inaccurate before sending.
          </p>

          <p className="text-xs text-gray-400">
            {result.input_tokens} input tokens · {result.output_tokens} output tokens
          </p>
        </div>
      )}
    </div>
  )
}
