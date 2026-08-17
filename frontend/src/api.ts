// ── Gọi SSE POST /api/chat/stream — parse event + xử lý lỗi 3 tầng ────────

import type { Source } from './types'

export interface StreamHandlers {
  onStatus: (text: string) => void
  onTool: (label: string) => void
  onToken: (token: string) => void
  onAnswer: (text: string) => void // answer / clarify — đè toàn bộ
  onSources: (sources: Source[]) => void
  onError: (msg: string) => void
  onDone: () => void
}

/** Đọc JSON lỗi từ FastAPI HTTPException: {detail: string} */
async function extractErrorDetail(res: Response): Promise<string> {
  try {
    const j = await res.json()
    if (typeof j?.detail === 'string') return j.detail
    if (Array.isArray(j?.detail)) {
      // pydantic ValidationError — ví dụ thiếu session_id
      return j.detail.map((d: { msg?: string }) => d.msg ?? '').join('; ')
    }
  } catch {
    /* không phải JSON */
  }
  return `Lỗi máy chủ (HTTP ${res.status})`
}

/**
 * Gọi stream chat. Không throw — mọi lỗi (4xx, network, error event)
 * đều đẩy vào onError để UI hiển thị + nút Thử lại.
 */
export async function streamChat(
  sessionId: string,
  message: string,
  history: { role: string; content: string }[],
  signal: AbortSignal,
  h: StreamHandlers,
): Promise<void> {
  let res: Response
  try {
    res = await fetch('/api/chat/stream', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ session_id: sessionId, message, history }),
      signal,
    })
  } catch (e) {
    if ((e as Error).name === 'AbortError') return // user bấm Stop — không phải lỗi
    h.onError('Mất kết nối tới máy chủ. Vui lòng thử lại.')
    return
  }

  // 4xx/5xx: hiện detail thật từ server (không nuốt lỗi như bản cũ)
  if (!res.ok) {
    h.onError(await extractErrorDetail(res))
    return
  }

  const reader = res.body?.getReader()
  if (!reader) {
    h.onError('Không nhận được phản hồi từ máy chủ.')
    return
  }

  const decoder = new TextDecoder()
  let buffer = ''
  try {
    while (true) {
      const { done, value } = await reader.read()
      if (done) break

      buffer += decoder.decode(value, { stream: true })
      const lines = buffer.split('\n')
      buffer = lines.pop() ?? ''

      for (const line of lines) {
        if (!line.startsWith('data: ')) continue
        let ev: Record<string, unknown>
        try {
          ev = JSON.parse(line.slice(6))
        } catch {
          continue
        }
        switch (ev.type) {
          case 'status':
            h.onStatus(String(ev.content ?? ''))
            break
          case 'tool_call': {
            const tool = String((ev.content as { tool?: string })?.tool ?? '')
            h.onTool(tool)
            break
          }
          case 'token':
            h.onToken(String(ev.content ?? ''))
            break
          case 'answer':
          case 'clarify':
            h.onAnswer(String(ev.content ?? ''))
            break
          case 'sources':
            h.onSources((ev.content as Source[]) ?? [])
            break
          case 'error':
            h.onError(String(ev.content ?? 'Có lỗi xảy ra khi xử lý câu hỏi.'))
            break
          case 'done':
            h.onDone()
            break
          default:
            break // decision, classify, ping → bỏ qua (không cần cho UI)
        }
      }
    }
  } catch (e) {
    if ((e as Error).name === 'AbortError') return
    h.onError('Kết nối bị gián đoạn. Vui lòng thử lại.')
  }
}
