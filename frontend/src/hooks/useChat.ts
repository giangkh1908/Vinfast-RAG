// ── State machine chat: idle → sending → streaming → done | error ─────────
// Chống spam Enter, nút Stop (AbortController), lỗi hiện rõ + Thử lại.
// Lưu ý: mọi side-effect localStorage đều NẰM NGOÀI setState updater
// (React StrictMode gọi updater 2 lần ở dev → tránh duplicate).

import { useCallback, useRef, useState } from 'react'
import { streamChat } from '../api'
import {
  clearSession,
  getHistory,
  getSessionId,
  getWindow,
  pushMessage,
  removeMessageById,
} from '../session'
import { toolLabel, type Message, type Source } from '../types'

export type Phase = 'idle' | 'sending' | 'streaming' | 'error'

export interface ChatState {
  phase: Phase
  messages: Message[]
  /** Text StatusBar — "Đang tra cứu giá xe…" — ẩn khi stream text đang chảy */
  statusText: string
  /** Đang có token nào rồi không (bỏ status khi có) */
  hasTokens: boolean
}

export function useChat() {
  const [state, setState] = useState<ChatState>(() => ({
    phase: 'idle',
    messages: getHistory().map((m) => ({
      ...m,
      status: 'done',
    })),
    statusText: '',
    hasTokens: false,
  }))

  const abortRef = useRef<AbortController | null>(null)
  /** Text assistant đang stream — dùng để lưu localStorage khi kết thúc */
  const contentRef = useRef('')
  /** Guard đồng bộ chống gửi trùng — closure `busy` bị stale khi Enter+click cùng tick */
  const busyRef = useRef(false)

  const patch = useCallback((p: Partial<ChatState>) => {
    setState((s) => ({ ...s, ...p }))
  }, [])

  const updateMsg = useCallback((id: string, p: Partial<Message>) => {
    setState((s) => ({
      ...s,
      messages: s.messages.map((m) => (m.id === id ? { ...m, ...p } : m)),
    }))
  }, [])

  const busy = state.phase === 'sending' || state.phase === 'streaming'

  const send = useCallback(
    async (text: string) => {
      const msg = text.trim()
      // Guard đồng bộ — KHÔNG dùng closure busy (stale khi 2 lần gọi cùng tick)
      if (!msg || busyRef.current) return
      busyRef.current = true

      const userMsg: Message = { id: crypto.randomUUID(), role: 'user', content: msg, status: 'done' }
      const asstMsg: Message = {
        id: crypto.randomUUID(),
        role: 'assistant',
        content: '',
        status: 'sending',
      }
      contentRef.current = ''

      setState((s) => ({
        ...s,
        phase: 'sending',
        statusText: 'Đang phân tích câu hỏi…',
        hasTokens: false,
        messages: [...s.messages, userMsg, asstMsg],
      }))
      pushMessage('user', msg, userMsg.id) // id khớp state — retry xoá đúng được

      const ac = new AbortController()
      abortRef.current = ac

      const sessionId = getSessionId()
      const window = getWindow() // đã gồm message vừa push (slice -14)

      try {
        await streamChat(
          sessionId,
          msg,
          window,
          ac.signal,
          {
            onStatus: (t) => {
              if (t) patch({ statusText: t })
            },
            onTool: (tool) => {
              // label thân thiện — user chỉ cần tiến độ, không cần tên tool
              patch({ statusText: toolLabel(tool) })
            },
            onToken: (token) => {
              contentRef.current += token
              setState((s) => ({
                ...s,
                phase: 'streaming',
                hasTokens: true,
                messages: s.messages.map((m) =>
                  m.id === asstMsg.id
                    ? { ...m, content: m.content + token, status: 'streaming' }
                    : m,
                ),
              }))
            },
            onAnswer: (answer) => {
              contentRef.current = answer
              patch({ phase: 'streaming', hasTokens: true })
              updateMsg(asstMsg.id, { content: answer, status: 'streaming' })
            },
            onSources: (sources: Source[]) => {
              updateMsg(asstMsg.id, { sources })
            },
            onError: (errMsg) => {
              // không lưu assistant lỗi vào localStorage — retry sẽ gửi lại sạch
              updateMsg(asstMsg.id, { status: 'error', error: errMsg, content: '' })
              contentRef.current = ''
              patch({ phase: 'error', statusText: '' })
            },
            onDone: () => {
              const finalContent = contentRef.current
              if (finalContent) {
                pushMessage('assistant', finalContent, asstMsg.id)
              }
              contentRef.current = ''
              setState((s) => ({
                ...s,
                phase: 'idle',
                statusText: '',
                hasTokens: false,
                messages: s.messages.map((x) =>
                  x.id === asstMsg.id
                    ? {
                        ...x,
                        status: finalContent ? 'done' : 'error',
                        error: finalContent ? undefined : 'Không có phản hồi.',
                      }
                    : x,
                ),
              }))
            },
          },
        )
      } finally {
        busyRef.current = false
        if (abortRef.current === ac) abortRef.current = null
      }
    },
    [patch, updateMsg], // bỏ busy khỏi deps — guard dùng busyRef
  )

  /** Nút ⏹ Stop: hủy request — chốt phần đã stream */
  const stop = useCallback(() => {
    abortRef.current?.abort()
    abortRef.current = null
    busyRef.current = false
    const partial = contentRef.current
    contentRef.current = ''
    if (partial) pushMessage('assistant', partial)
    setState((s) => ({
      ...s,
      phase: 'idle',
      statusText: '',
      hasTokens: false,
      messages: s.messages.map((m) =>
        m.role === 'assistant' && (m.status === 'sending' || m.status === 'streaming')
          ? { ...m, content: partial, status: 'done' }
          : m,
      ),
    }))
  }, [])

  /** Thử lại: xoá turn lỗi (user + assistant error) khỏi state & storage, gửi lại */
  const retry = useCallback(() => {
    const lastUser = [...state.messages].reverse().find((m) => m.role === 'user')
    if (!lastUser) return
    // xoá khỏi localStorage message user bị lỗi (sẽ được push lại bởi send)
    removeMessageById(lastUser.id)
    // xoá turn lỗi khỏi state: assistant error cuối + user cuối
    setState((s) => {
      const msgs = [...s.messages]
      while (msgs.length && msgs[msgs.length - 1].role === 'assistant' && msgs[msgs.length - 1].status === 'error') {
        msgs.pop()
      }
      if (msgs.length && msgs[msgs.length - 1].role === 'user') msgs.pop()
      return { ...s, messages: msgs, phase: 'idle', statusText: '', hasTokens: false }
    })
    void send(lastUser.content)
  }, [send, state.messages])

  /** "Chat mới": xoá session + history */
  const clearChat = useCallback(() => {
    abortRef.current?.abort()
    abortRef.current = null
    contentRef.current = ''
    clearSession()
    setState({ phase: 'idle', messages: [], statusText: '', hasTokens: false })
  }, [])

  return { ...state, busy, send, stop, retry, clearChat }
}
