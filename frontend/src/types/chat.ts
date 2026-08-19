// ── Types khớp backend (app/agent + app/api/chat.py) ──────────────────────

export interface Source {
  text: string
  url: string
  type?: string
  score?: number
}

export type MessageStatus = 'sending' | 'streaming' | 'done' | 'error'

export interface Message {
  id: string // uuid client — React key + dedupe
  role: 'user' | 'assistant'
  content: string
  status: MessageStatus
  error?: string
  sources?: Source[]
}

/** Dạng lưu trong localStorage (tối giản) */
export interface StoredMsg {
  id: string
  role: 'user' | 'assistant'
  content: string
}

/** Event SSE từ POST /api/chat/stream */
export type StreamEvent =
  | { type: 'decision'; content: string }
  | { type: 'classify'; content: unknown }
  | { type: 'status'; content: string } // "Đang tra cứu dữ liệu…"
  | { type: 'tool_call'; content: { tool: string; success: boolean } }
  | { type: 'token'; content: string }
  | { type: 'answer'; content: string }
  | { type: 'clarify'; content: string }
  | { type: 'sources'; content: Source[] }
  | { type: 'error'; content: string }
  | { type: 'ping' } // heartbeat — bỏ qua
  | { type: 'done' }

/** Bản đồ tool → label thân thiện. User chỉ cần TIẾN ĐỘ, không cần tên kỹ thuật. */
export const TOOL_LABELS: Record<string, string> = {
  get_price: 'Đang tra cứu giá xe…',
  get_specs: 'Đang tra cứu thông số kỹ thuật…',
  get_colors: 'Đang tra cứu màu sắc…',
  list_available_models: 'Đang tải danh sách xe…',
  search_knowledge_base: 'Đang tra cứu dữ liệu…',
  ask_clarification: 'Đang làm rõ câu hỏi…',
}

/** Fallback cho tool chưa có trong map — KHÔNG bao giờ hiện tên tool */
export const TOOL_LABEL_FALLBACK = 'Đang tra cứu dữ liệu…'

export function toolLabel(tool: string): string {
  return TOOL_LABELS[tool] ?? TOOL_LABEL_FALLBACK
}
