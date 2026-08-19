import '@testing-library/jest-dom/vitest'
import { cleanup } from '@testing-library/react'
import { afterEach, vi } from 'vitest'

afterEach(() => {
  cleanup()
  localStorage.clear()
  vi.clearAllMocks()
})

// Polyfill crypto.randomUUID for test environment
if (typeof crypto.randomUUID !== 'function') {
  let count = 0
  crypto.randomUUID = () => `00000000-0000-4000-8000-${String(++count).padStart(12, '0')}` as `${string}-${string}-${string}-${string}-${string}`
}
