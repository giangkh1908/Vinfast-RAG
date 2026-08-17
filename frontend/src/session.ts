// ── Session + history trong localStorage (xem docs/MEMORY_PLAN.md) ─────────
// - vivu_session_id: uuid, tạo 1 lần — "clear chat" = xoá + tạo mới
// - vivu_history: [{id, role, content}] — toàn bộ hội thoại (UI + gửi window)
// - Server gửi window = history.slice(-14) = 7 turn (đã chốt)

import type { StoredMsg } from './types'

const SID_KEY = 'vivu_session_id'
const HIST_KEY = 'vivu_history'

function newId(): string {
  return crypto.randomUUID()
}

export function getSessionId(): string {
  let sid = localStorage.getItem(SID_KEY)
  if (!sid) {
    sid = newId()
    localStorage.setItem(SID_KEY, sid)
  }
  return sid
}

export function getHistory(): StoredMsg[] {
  try {
    const raw = localStorage.getItem(HIST_KEY)
    if (!raw) return []
    const parsed = JSON.parse(raw)
    return Array.isArray(parsed) ? parsed : []
  } catch {
    return []
  }
}

function saveHistory(hist: StoredMsg[]): void {
  localStorage.setItem(HIST_KEY, JSON.stringify(hist))
}

/** Thêm message. id truyền vào để khớp với id trong state (React) */
export function pushMessage(role: 'user' | 'assistant', content: string, id?: string): StoredMsg {
  const msg: StoredMsg = { id: id ?? newId(), role, content }
  const hist = getHistory()
  hist.push(msg)
  saveHistory(hist)
  return msg
}

/** Xoá message theo id (dùng khi retry — bỏ turn lỗi, tránh duplicate) */
export function removeMessageById(id: string): void {
  saveHistory(getHistory().filter((m) => m.id !== id))
}

/** Window gửi lên server: 7 turn = 14 message cuối (quy ước từ MEMORY_PLAN) */
export function getWindow(): { role: string; content: string }[] {
  return getHistory()
    .slice(-14)
    .map((m) => ({ role: m.role, content: m.content }))
}

/** "Chat mới": xoá hết + tạo session_id mới */
export function clearSession(): string {
  localStorage.removeItem(SID_KEY)
  localStorage.removeItem(HIST_KEY)
  return getSessionId()
}
