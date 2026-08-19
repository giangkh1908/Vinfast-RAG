import { useState, useRef, useEffect, useCallback } from 'react'

interface SpeechOptions {
  onTranscript: (text: string, isFinal: boolean) => void
  onError?: (errorMessage: string) => void
}

// Minimal typing for Web Speech API
interface IWindowSpeech extends Window {
  SpeechRecognition?: any
  webkitSpeechRecognition?: any
}

export function useSpeechToText({ onTranscript, onError }: SpeechOptions) {
  const [isListening, setIsListening] = useState(false)
  const [error, setError] = useState<string | null>(null)
  const recognitionRef = useRef<any>(null)

  const isSupported =
    typeof window !== 'undefined' &&
    Boolean(
      (window as IWindowSpeech).SpeechRecognition ||
      (window as IWindowSpeech).webkitSpeechRecognition
    )

  const stopListening = useCallback(() => {
    if (recognitionRef.current) {
      try {
        recognitionRef.current.stop()
      } catch {
        // Ignore if already stopped
      }
      recognitionRef.current = null
    }
    setIsListening(false)
  }, [])

  const startListening = useCallback(() => {
    if (!isSupported) {
      const msg = 'Trình duyệt không hỗ trợ nhận diện giọng nói (Web Speech API).'
      setError(msg)
      onError?.(msg)
      return
    }

    // Stop any existing session
    stopListening()
    setError(null)

    try {
      const win = window as IWindowSpeech
      const SpeechRecognitionClass = win.SpeechRecognition || win.webkitSpeechRecognition
      const recognition = new SpeechRecognitionClass()

      recognition.lang = 'vi-VN'
      recognition.interimResults = true
      recognition.continuous = false
      recognition.maxAlternatives = 1

      recognition.onstart = () => {
        setIsListening(true)
      }

      recognition.onresult = (event: any) => {
        let interimText = ''
        let finalText = ''

        for (let i = event.resultIndex; i < event.results.length; ++i) {
          const res = event.results[i]
          if (res.isFinal) {
            finalText += res[0].transcript
          } else {
            interimText += res[0].transcript
          }
        }

        const currentText = finalText || interimText
        if (currentText) {
          onTranscript(currentText, Boolean(finalText))
        }
      }

      recognition.onerror = (event: any) => {
        let msg = 'Đã có lỗi khi nhận diện giọng nói.'
        if (event.error === 'not-allowed' || event.error === 'service-not-allowed') {
          msg = 'Vui lòng cấp quyền truy cập Microphone trên trình duyệt để sử dụng.'
        } else if (event.error === 'no-speech') {
          msg = 'Không phát hiện giọng nói. Vui lòng thử lại gần microphone hơn.'
        }
        setError(msg)
        onError?.(msg)
        setIsListening(false)
      }

      recognition.onend = () => {
        setIsListening(false)
        recognitionRef.current = null
      }

      recognitionRef.current = recognition
      recognition.start()
    } catch (err: any) {
      const msg = err?.message || 'Không thể khởi động Microphone.'
      setError(msg)
      onError?.(msg)
      setIsListening(false)
    }
  }, [isSupported, onError, onTranscript, stopListening])

  const toggleListening = useCallback(() => {
    if (isListening) {
      stopListening()
    } else {
      startListening()
    }
  }, [isListening, startListening, stopListening])

  useEffect(() => {
    return () => {
      if (recognitionRef.current) {
        try {
          recognitionRef.current.abort()
        } catch {
          // Cleanup
        }
      }
    }
  }, [])

  return {
    isListening,
    isSupported,
    error,
    startListening,
    stopListening,
    toggleListening,
  }
}
