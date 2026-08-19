import { renderHook, act } from '@testing-library/react'
import { describe, it, expect, beforeEach, vi } from 'vitest'
import { useTheme } from '../useTheme'

describe('useTheme hook', () => {
  beforeEach(() => {
    localStorage.clear()
    // Mock window.matchMedia
    window.matchMedia = vi.fn().mockImplementation((query) => ({
      matches: false,
      media: query,
      onchange: null,
      addListener: vi.fn(),
      removeListener: vi.fn(),
      addEventListener: vi.fn(),
      removeEventListener: vi.fn(),
      dispatchEvent: vi.fn(),
    }))
  })

  it('defaults to light theme when localStorage is empty', () => {
    const { result } = renderHook(() => useTheme())
    expect(result.current.theme).toBe('light')
    expect(result.current.resolvedTheme).toBe('light')
  })

  it('toggles theme from light to dark and persists to localStorage', () => {
    const { result } = renderHook(() => useTheme())

    act(() => {
      result.current.toggleTheme()
    })

    expect(result.current.resolvedTheme).toBe('dark')
    expect(localStorage.getItem('vivu-chat-theme')).toBe('dark')

    act(() => {
      result.current.toggleTheme()
    })

    expect(result.current.resolvedTheme).toBe('light')
    expect(localStorage.getItem('vivu-chat-theme')).toBe('light')
  })

  it('loads saved theme from localStorage', () => {
    localStorage.setItem('vivu-chat-theme', 'dark')
    const { result } = renderHook(() => useTheme())
    expect(result.current.theme).toBe('dark')
    expect(result.current.resolvedTheme).toBe('dark')
  })
})
