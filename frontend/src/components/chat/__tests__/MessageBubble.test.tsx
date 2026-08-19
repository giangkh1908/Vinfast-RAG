import { render, screen, fireEvent } from '@testing-library/react'
import { describe, it, expect } from 'vitest'
import MessageBubble from '../MessageBubble'
import type { Message } from '../../../types'

describe('MessageBubble Component', () => {
  it('renders user message correctly', () => {
    const msg: Message = {
      id: 'msg-user-1',
      role: 'user',
      content: 'VF 8 giá bao nhiêu vậy bot?',
      status: 'done',
    }

    render(<MessageBubble msg={msg} />)
    expect(screen.getByText('Bạn')).toBeInTheDocument()
    expect(screen.getByText('VF 8 giá bao nhiêu vậy bot?')).toBeInTheDocument()
  })

  it('renders error assistant message correctly', () => {
    const msg: Message = {
      id: 'msg-asst-err',
      role: 'assistant',
      content: '',
      status: 'error',
      error: 'Máy chủ tạm thời bận. Vui lòng thử lại sau.',
    }

    render(<MessageBubble msg={msg} />)
    expect(screen.getByText('VinFast')).toBeInTheDocument()
    expect(screen.getByText('Máy chủ tạm thời bận. Vui lòng thử lại sau.')).toBeInTheDocument()
  })

  it('returns null for pending assistant message with empty content', () => {
    const msg: Message = {
      id: 'msg-asst-pending',
      role: 'assistant',
      content: '',
      status: 'sending',
    }

    const { container } = render(<MessageBubble msg={msg} />)
    expect(container.firstChild).toBeNull()
  })

  it('renders markdown response and safe links', () => {
    const msg: Message = {
      id: 'msg-asst-md',
      role: 'assistant',
      content: '### Bảng giá VF 8\n- **Eco**: 1.090.000.000 VNĐ\n- [Trang đặt cọc](https://shop.vinfastauto.com)',
      status: 'done',
    }

    render(<MessageBubble msg={msg} />)
    expect(screen.getByText('Bảng giá VF 8')).toBeInTheDocument()
    expect(screen.getByText('Eco')).toBeInTheDocument()

    const link = screen.getByRole('link', { name: 'Trang đặt cọc' })
    expect(link).toHaveAttribute('href', 'https://shop.vinfastauto.com')
    expect(link).toHaveAttribute('target', '_blank')
    expect(link).toHaveAttribute('rel', 'noopener noreferrer')
  })

  it('handles long text truncation and expansion toggle', () => {
    const longContent = 'VinFast VF 8 là mẫu SUV điện cỡ D cao cấp. '.repeat(25) // > 500 chars
    const msg: Message = {
      id: 'msg-asst-long',
      role: 'assistant',
      content: longContent,
      status: 'done',
    }

    render(<MessageBubble msg={msg} />)

    // Initial state: truncated with "Xem thêm ▼"
    const toggleBtn = screen.getByText('Xem thêm ▼')
    expect(toggleBtn).toBeInTheDocument()

    // Click "Xem thêm ▼" -> expands and shows "Thu gọn ▲"
    fireEvent.click(toggleBtn)
    expect(screen.getByText('Thu gọn ▲')).toBeInTheDocument()

    // Click "Thu gọn ▲" -> collapses
    fireEvent.click(screen.getByText('Thu gọn ▲'))
    expect(screen.getByText('Xem thêm ▼')).toBeInTheDocument()
  })

  it('renders sources box when sources are provided', () => {
    const msg: Message = {
      id: 'msg-asst-sources',
      role: 'assistant',
      content: 'VF 8 có tầm di chuyển 471 km.',
      status: 'done',
      sources: [
        {
          text: 'Thông số kỹ thuật VF 8',
          url: 'https://vinfastauto.com/vn_vi/thong-so-vf8',
          type: 'specs',
          score: 0.9,
        },
      ],
    }

    render(<MessageBubble msg={msg} />)
    expect(screen.getByText('Nguồn tham khảo (1)')).toBeInTheDocument()
  })

  it('renders GFM Markdown table with accessible region', () => {
    const tableMarkdown = `
| Dòng xe | Phân khúc | Tầm hoạt động |
| --- | --- | --- |
| VF 3 | Mini SUV | 215 km |
| VF 7 | C-SUV | 496 km |
`
    const msg: Message = {
      id: 'msg-asst-table',
      role: 'assistant',
      content: tableMarkdown,
      status: 'done',
    }

    render(<MessageBubble msg={msg} />)
    expect(screen.getByRole('region', { name: 'Bảng số liệu' })).toBeInTheDocument()
    expect(screen.getByText('Dòng xe')).toBeInTheDocument()
    expect(screen.getByText('VF 3')).toBeInTheDocument()
    expect(screen.getByText('215 km')).toBeInTheDocument()
  })

  it('renders code block with Copy button', () => {
    const codeMarkdown = '```python\nprice = 1090000000\n```'
    const msg: Message = {
      id: 'msg-asst-code',
      role: 'assistant',
      content: codeMarkdown,
      status: 'done',
    }

    render(<MessageBubble msg={msg} />)
    expect(screen.getByText('python')).toBeInTheDocument()
    expect(screen.getByRole('button', { name: 'Sao chép khối mã' })).toBeInTheDocument()
  })
})
