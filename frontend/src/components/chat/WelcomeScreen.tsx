interface Props {
  onSelectPrompt: (prompt: string) => void
}

const SAMPLE_PROMPTS = [
  {
    icon: '🚗',
    title: 'Thông số VF 3',
    prompt: 'Cho tôi biết thông số kỹ thuật xe VinFast VF 3',
  },
  {
    icon: '💰',
    title: 'Bảng giá xe điện',
    prompt: 'Bảng giá các dòng xe ô tô điện VinFast mới nhất hiện nay',
  },
  {
    icon: '🔋',
    title: 'Chính sách bảo hành pin',
    prompt: 'Chính sách thuê pin và bảo hành xe ô tô điện VinFast thế nào?',
  },
  {
    icon: '⚡',
    title: 'So sánh VF 6 & VF 7',
    prompt: 'So sánh chi tiết xe VinFast VF 6 và VF 7',
  },
]

export default function WelcomeScreen({ onSelectPrompt }: Props) {
  return (
    <div id="welcome_screen" className="cw_body welcome_screen_container">
      <div className="welcome_header">
        <div className="welcome_avatar_glow">
          <img
            id="welcome_screen_image"
            src="./images/vivi-avatar.png"
            onError={(e) => {
              e.currentTarget.src = 'https://cdn-media.vinbase.ai/avatar/20250313024710_4.png'
            }}
            alt="VinFast Vivi"
          />
        </div>
        <div id="welcome_screen_slogan" className="welcome_slogan">
          VinFast — Cùng bạn bứt phá mọi giới hạn
        </div>
        <div id="welcome_screen_message" className="welcome_message">
          Xin chào Quý khách! Vivi rất vui được hỗ trợ. Quý khách đang quan tâm đến dòng xe hoặc dịch vụ nào của VinFast?
        </div>
      </div>

      <div className="welcome_prompts_section">
        <div className="welcome_prompts_title">Gợi ý câu hỏi nhanh:</div>
        <div className="welcome_prompts_grid">
          {SAMPLE_PROMPTS.map((item, index) => (
            <button
              key={index}
              className="welcome_prompt_card"
              onClick={() => onSelectPrompt(item.prompt)}
            >
              <span className="prompt_icon">{item.icon}</span>
              <span className="prompt_text">{item.title}</span>
            </button>
          ))}
        </div>
      </div>
    </div>
  )
}
