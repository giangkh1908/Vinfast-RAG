import { render, screen, fireEvent } from '@testing-library/react'
import { describe, it, expect, vi } from 'vitest'
import InputBar from '../InputBar'

describe('InputBar Component', () => {
  it('renders input field, suggestions, and buttons', () => {
    const handleSend = vi.fn()
    const handleNewTopic = vi.fn()

    render(<InputBar busy={false} onSend={handleSend} onNewTopic={handleNewTopic} />)

    expect(screen.getByPlaceholderText('Nhập tin nhắn hỏi về xe VinFast...')).toBeInTheDocument()
    expect(screen.getByText('Bảng giá VF 3')).toBeInTheDocument()
    expect(screen.getByText('Thông số VF 7')).toBeInTheDocument()
  })

  it('handles typing and submits on Enter key', () => {
    const handleSend = vi.fn()
    const handleNewTopic = vi.fn()

    render(<InputBar busy={false} onSend={handleSend} onNewTopic={handleNewTopic} />)

    const input = screen.getByPlaceholderText('Nhập tin nhắn hỏi về xe VinFast...')
    fireEvent.change(input, { target: { value: 'VF 8 giá bao nhiêu?' } })
    expect(input).toHaveValue('VF 8 giá bao nhiêu?')

    fireEvent.keyDown(input, { key: 'Enter', code: 'Enter' })
    expect(handleSend).toHaveBeenCalledWith('VF 8 giá bao nhiêu?')
    expect(input).toHaveValue('')
  })

  it('submits on send button click', () => {
    const handleSend = vi.fn()
    const handleNewTopic = vi.fn()

    render(<InputBar busy={false} onSend={handleSend} onNewTopic={handleNewTopic} />)

    const input = screen.getByPlaceholderText('Nhập tin nhắn hỏi về xe VinFast...')
    fireEvent.change(input, { target: { value: 'So sánh VF 6 và VF 7' } })

    const sendBtn = screen.getByTitle('Gửi tin nhắn')
    fireEvent.click(sendBtn)
    expect(handleSend).toHaveBeenCalledWith('So sánh VF 6 và VF 7')
  })

  it('triggers onSend when clicking suggestion chip', () => {
    const handleSend = vi.fn()
    const handleNewTopic = vi.fn()

    render(<InputBar busy={false} onSend={handleSend} onNewTopic={handleNewTopic} />)

    const chip = screen.getByText('Bảng giá VF 3')
    fireEvent.click(chip)
    expect(handleSend).toHaveBeenCalledWith('Bảng giá VF 3')
  })

  it('toggles emoji picker and selects emoji into input', () => {
    const handleSend = vi.fn()
    const handleNewTopic = vi.fn()

    render(<InputBar busy={false} onSend={handleSend} onNewTopic={handleNewTopic} />)

    const emojiBtn = screen.getByTitle('Biểu tượng cảm xúc')
    fireEvent.click(emojiBtn)

    // Emoji picker is now open
    const carEmoji = screen.getByText('🚗')
    expect(carEmoji).toBeInTheDocument()

    fireEvent.click(carEmoji)
    const input = screen.getByPlaceholderText('Nhập tin nhắn hỏi về xe VinFast...')
    expect(input).toHaveValue('🚗')
  })

  it('triggers onNewTopic on button click', () => {
    const handleSend = vi.fn()
    const handleNewTopic = vi.fn()

    render(<InputBar busy={false} onSend={handleSend} onNewTopic={handleNewTopic} />)

    const newTopicBtn = screen.getByTitle('Tạo chủ đề mới')
    fireEvent.click(newTopicBtn)
    expect(handleNewTopic).toHaveBeenCalledTimes(1)
  })

  it('disables input and suggestion chips when busy', () => {
    const handleSend = vi.fn()
    const handleNewTopic = vi.fn()

    render(<InputBar busy={true} onSend={handleSend} onNewTopic={handleNewTopic} />)

    const input = screen.getByPlaceholderText('Nhập tin nhắn hỏi về xe VinFast...')
    expect(input).toBeDisabled()

    const chip = screen.getByText('Bảng giá VF 3')
    expect(chip).toBeDisabled()

    fireEvent.click(chip)
    expect(handleSend).not.toHaveBeenCalled()
  })
})
