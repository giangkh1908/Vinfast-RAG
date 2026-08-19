import { renderHook, act } from '@testing-library/react'
import { describe, it, expect, vi, beforeEach } from 'vitest'
import { useChat } from '../useChat'
import * as api from '../../api'
import * as session from '../../session'

vi.mock('../../api', () => ({
  streamChat: vi.fn(),
}))

describe('useChat Hook', () => {
  beforeEach(() => {
    localStorage.clear()
    vi.clearAllMocks()
  })

  it('initializes with idle phase and empty messages when localStorage is empty', () => {
    const { result } = renderHook(() => useChat())
    expect(result.current.phase).toBe('idle')
    expect(result.current.messages).toEqual([])
    expect(result.current.busy).toBe(false)
    expect(result.current.statusText).toBe('')
    expect(result.current.hasTokens).toBe(false)
  })

  it('loads initial history from localStorage', () => {
    session.pushMessage('user', 'Tin nhắn cũ 1', 'msg-1')
    session.pushMessage('assistant', 'Trả lời cũ 1', 'msg-2')

    const { result } = renderHook(() => useChat())
    expect(result.current.messages).toHaveLength(2)
    expect(result.current.messages[0].content).toBe('Tin nhắn cũ 1')
    expect(result.current.messages[1].content).toBe('Trả lời cũ 1')
    expect(result.current.messages[0].status).toBe('done')
  })

  it('transitions state correctly on successful stream', async () => {
    vi.useFakeTimers()
    const mockStreamChat = vi.mocked(api.streamChat)

    mockStreamChat.mockImplementation(async (_sid, _msg, _win, _sig, handlers) => {
      handlers.onStatus('Đang phân tích câu hỏi…')
      handlers.onToken('VF 8 ')
      handlers.onToken('giá 1 tỷ.')
      handlers.onDone()
    })

    const { result } = renderHook(() => useChat())

    await act(async () => {
      void result.current.send('VF 8 giá bao nhiêu?')
    })

    expect(mockStreamChat).toHaveBeenCalledTimes(1)

    // Fast-forward timers for word-boundary buffer flush
    act(() => {
      vi.runAllTimers()
    })

    expect(result.current.phase).toBe('idle')
    expect(result.current.messages).toHaveLength(2)
    expect(result.current.messages[0].role).toBe('user')
    expect(result.current.messages[0].content).toBe('VF 8 giá bao nhiêu?')
    expect(result.current.messages[1].role).toBe('assistant')
    expect(result.current.messages[1].status).toBe('done')
    expect(result.current.messages[1].content).toBe('VF 8 giá 1 tỷ.')

    vi.useRealTimers()
  })

  it('handles error response and transitions to error phase', async () => {
    const mockStreamChat = vi.mocked(api.streamChat)
    mockStreamChat.mockImplementation(async (_sid, _msg, _win, _sig, handlers) => {
      handlers.onError('Lỗi kết nối máy chủ')
    })

    const { result } = renderHook(() => useChat())

    await act(async () => {
      await result.current.send('VF 8')
    })

    expect(result.current.phase).toBe('error')
    expect(result.current.messages).toHaveLength(2)
    expect(result.current.messages[1].status).toBe('error')
    expect(result.current.messages[1].error).toBe('Lỗi kết nối máy chủ')
  })

  it('aborts active stream on stop()', async () => {
    const mockStreamChat = vi.mocked(api.streamChat)
    mockStreamChat.mockImplementation(async (_sid, _msg, _win, signal, handlers) => {
      handlers.onToken('Đang trả lời một phần...')
      return new Promise((resolve) => {
        signal.addEventListener('abort', () => resolve())
      })
    })

    const { result } = renderHook(() => useChat())

    act(() => {
      void result.current.send('VF 8')
    })

    act(() => {
      result.current.stop()
    })

    expect(result.current.phase).toBe('idle')
    expect(result.current.busy).toBe(false)
  })

  it('clears session and history on clearChat()', () => {
    session.pushMessage('user', 'Câu hỏi', 'msg-1')
    const { result } = renderHook(() => useChat())
    expect(result.current.messages).toHaveLength(1)

    act(() => {
      result.current.clearChat()
    })

    expect(result.current.messages).toEqual([])
    expect(result.current.phase).toBe('idle')
    expect(session.getHistory()).toEqual([])
  })

  it('retries last failed message on retry()', async () => {
    const mockStreamChat = vi.mocked(api.streamChat)
    let attempt = 0

    mockStreamChat.mockImplementation(async (_sid, _msg, _win, _sig, handlers) => {
      attempt++
      if (attempt === 1) {
        handlers.onError('Lỗi lần 1')
      } else {
        handlers.onToken('Thành công lần 2')
        handlers.onDone()
      }
    })

    const { result } = renderHook(() => useChat())

    // First attempt -> fails
    await act(async () => {
      await result.current.send('Câu hỏi retry')
    })
    expect(result.current.messages[1].status).toBe('error')

    // Retry -> succeeds
    await act(async () => {
      result.current.retry()
    })

    expect(mockStreamChat).toHaveBeenCalledTimes(2)
  })
})
