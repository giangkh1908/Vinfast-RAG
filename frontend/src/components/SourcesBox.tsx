import type { Source } from '../types'

export default function SourcesBox({ sources }: { sources?: Source[] }) {
  if (!sources || sources.length === 0) return null
  return (
    <details className="sources-box">
      <summary className="sources-summary">
        <i className="mdi mdi-book-open-page-variant-outline"></i>
        <span>Nguồn tham khảo ({sources.length})</span>
        <i className="mdi mdi-chevron-down summary-arrow"></i>
      </summary>
      <div className="sources-list">
        {sources.map((s, i) => (
          <div key={i} className="source-item">
            <a href={s.url} target="_blank" rel="noopener noreferrer" className="source-link">
              <i className="mdi mdi-link-variant"></i>
              <span className="source-title">{s.text || s.url}</span>
              {typeof s.score === 'number' && (
                <span className="source-score">{Math.round(s.score * 100)}%</span>
              )}
            </a>
          </div>
        ))}
      </div>
    </details>
  )
}
