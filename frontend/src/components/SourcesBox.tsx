import type { Source } from '../types'

export default function SourcesBox({ sources }: { sources?: Source[] }) {
  if (!sources || sources.length === 0) return null
  return (
    <details className="sources" open>
      <summary>Nguồn tham khảo ({sources.length})</summary>
      {sources.map((s, i) => (
        <div key={i} style={{ marginTop: 4, fontSize: 13 }}>
          <a href={s.url} target="_blank" rel="noopener noreferrer">
            {s.text || s.url}
            {typeof s.score === 'number' ? ` (${Math.round(s.score * 100)}%)` : ''}
          </a>
        </div>
      ))}
    </details>
  )
}
