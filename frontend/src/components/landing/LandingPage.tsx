interface Props {
  onOpenChat: (initialPrompt?: string) => void
}

interface CarModel {
  name: string
  segment: string
  range: string
  power: string
  image: string
  tag?: string
  prompt: string
}

const CAR_MODELS: CarModel[] = [
  {
    name: 'VinFast VF 3',
    segment: 'Mini SUV đô thị',
    range: '215 km',
    power: '43 mã lực',
    image: './images/cars/vf3.jpg',
    tag: 'Bán chạy nhất',
    prompt: 'Tư vấn thông số kỹ thuật, giá bán và ưu đãi mới nhất của xe VinFast VF 3',
  },
  {
    name: 'VinFast VF 5 Plus',
    segment: 'A-SUV Đô thị linh hoạt',
    range: '326 km',
    power: '134 mã lực',
    image: './images/cars/vf5.jpg',
    tag: 'Tiết kiệm & Đa dụng',
    prompt: 'Cho tôi biết thông số kỹ thuật và giá xe VinFast VF 5 Plus',
  },
  {
    name: 'VinFast VF 6',
    segment: 'B-SUV Gia đình hiện đại',
    range: '399 km',
    power: '201 mã lực',
    image: './images/cars/vf6.jpg',
    tag: 'Thiết kế thời thượng',
    prompt: 'Tư vấn thông số, tiện nghi và giá bán xe VinFast VF 6',
  },
  {
    name: 'VinFast VF 7',
    segment: 'C-SUV Thể thao bứt phá',
    range: '496 km',
    power: '349 mã lực',
    image: './images/cars/vf7.jpg',
    tag: 'Cảm giác lái đỉnh cao',
    prompt: 'So sánh các phiên bản và bảng giá lăn bánh VinFast VF 7',
  },
  {
    name: 'VinFast VF 8',
    segment: 'D-SUV Điện thông minh',
    range: '471 km',
    power: '402 mã lực',
    image: './images/cars/vf8.jpg',
    tag: 'Đẳng cấp toàn cầu',
    prompt: 'Tư vấn thông số kỹ thuật, hệ thống ADAS và giá bán VinFast VF 8 mới nhất',
  },
  {
    name: 'VinFast VF 9',
    segment: 'E-SUV Hạng sang 7 chỗ',
    range: '626 km',
    power: '402 mã lực',
    image: './images/cars/vf9.jpg',
    tag: 'Chủ tịch & Doanh nhân',
    prompt: 'Tư vấn trang bị cao cấp, không gian và chính sách ưu đãi xe VinFast VF 9',
  },
]

export default function LandingPage({ onOpenChat }: Props) {
  return (
    <div className="vin-landing">
      {/* ── Top Header Navigation ──────────────────────────────── */}
      <header className="landing-navbar">
        <div className="navbar-container">
          <div className="navbar-logo">
            {/* VinFast V Logo SVG */}
            <svg width="40" height="32" viewBox="0 0 110 90" fill="none" xmlns="http://www.w3.org/2000/svg">
              <path
                d="M55 90L0 0H24L55 58L86 0H110L55 90Z"
                fill="#1462D6"
              />
              <path
                d="M55 70L20 12H38L55 46L72 12H90L55 70Z"
                fill="#0040BF"
              />
            </svg>
            <span className="logo-text">VINFAST</span>
          </div>

          <nav className="navbar-menu">
            <a href="#cars" className="nav-link active">Ô tô điện</a>
            <a href="#ecosystem" className="nav-link">Pin & Trạm sạc</a>
            <a href="#services" className="nav-link">Dịch vụ & Hậu mãi</a>
            <a href="#promotions" className="nav-link">Ưu đãi</a>
            <a href="https://vinfastauto.com/vn_vi" target="_blank" rel="noreferrer" className="nav-link">
              Trang chủ VinFast <i className="mdi mdi-open-in-new" style={{ fontSize: 13 }}></i>
            </a>
          </nav>

          <div className="navbar-actions">
            <button
              className="nav-consult-btn"
              onClick={() => onOpenChat('Xin chào, tôi cần tư vấn các dòng xe VinFast')}
            >
              <i className="mdi mdi-chat-processing-outline"></i>
              <span>Tư vấn cùng Vivi</span>
            </button>
            <div className="nav-hotline">
              <i className="mdi mdi-phone"></i>
              <span>1900 23 23 89</span>
            </div>
          </div>
        </div>
      </header>

      {/* ── Hero Banner Section ────────────────────────────────── */}
      <section className="landing-hero">
        <div className="hero-overlay"></div>
        <div className="hero-content">
          <span className="hero-badge">VINFAST ELECTRIC VEHICLES</span>
          <h1 className="hero-title">MÃNH LIỆT TINH THẦN VIỆT NAM</h1>
          <p className="hero-subtitle">
            Khám phá dải sản phẩm ô tô điện thông minh, tiên phong kiến tạo tương lai di chuyển xanh
          </p>
          <div className="hero-cta-group">
            <button
              className="hero-btn-primary"
              onClick={() => onOpenChat('Hãy so sánh các dòng xe điện VinFast để tôi chọn xe phù hợp')}
            >
              <i className="mdi mdi-sparkles"></i> Tư vấn chọn xe với AI
            </button>
            <a href="#cars" className="hero-btn-outline">
              Khám phá các dòng xe <i className="mdi mdi-arrow-down"></i>
            </a>
          </div>
        </div>
      </section>

      {/* ── Car Models Grid Section ────────────────────────────── */}
      <section id="cars" className="landing-cars-section">
        <div className="section-header">
          <h2 className="section-title">DẢI SẢN PHẨM Ô TÔ ĐIỆN VINFAST</h2>
          <p className="section-desc">
            Đa dạng phân khúc từ mini đô thị đến SUV 7 chỗ hạng sang đỉnh cao công nghệ
          </p>
        </div>

        <div className="cars-grid">
          {CAR_MODELS.map((car, idx) => (
            <div key={idx} className="car-card">
              {car.tag && <span className="car-tag">{car.tag}</span>}
              <div className="car-image-wrapper">
                <img
                  src={car.image}
                  alt={car.name}
                  className="car-image"
                  loading="lazy"
                  onError={(e) => {
                    // Fallback visual icon if image fails
                    const target = e.currentTarget
                    target.style.display = 'none'
                  }}
                />
              </div>
              <div className="car-info">
                <div className="car-segment">{car.segment}</div>
                <h3 className="car-name">{car.name}</h3>

                <div className="car-specs-row">
                  <div className="spec-item">
                    <i className="mdi mdi-battery-charging-outline"></i>
                    <span>{car.range}</span>
                  </div>
                  <div className="spec-item">
                    <i className="mdi mdi-speedometer"></i>
                    <span>{car.power}</span>
                  </div>
                </div>

                <button
                  className="car-consult-btn"
                  onClick={() => onOpenChat(car.prompt)}
                >
                  <i className="mdi mdi-message-text-outline"></i>
                  Hỏi trợ lý về {car.name.replace('VinFast ', '')}
                </button>
              </div>
            </div>
          ))}
        </div>
      </section>

      {/* ── Eco-system & Benefits Section ──────────────────────── */}
      <section id="ecosystem" className="landing-ecosystem">
        <div className="ecosystem-container">
          <div className="ecosystem-header">
            <h2>HỆ SINH THÁI XE ĐIỆN TOÀN DIỆN</h2>
            <p>Cam kết mang lại trải nghiệm an tâm trọn vẹn nhất cho khách hàng</p>
          </div>
          <div className="ecosystem-grid">
            <div className="eco-card" onClick={() => onOpenChat('Hệ thống trạm sạc VinFast phủ sóng ở đâu?')}>
              <div className="eco-icon"><i className="mdi mdi-ev-station"></i></div>
              <h3>150.000+ Cổng sạc</h3>
              <p>Mạng lưới trạm sạc phủ khắp 63 tỉnh thành, các tuyến cao tốc và khu đô thị</p>
            </div>
            <div className="eco-card" onClick={() => onOpenChat('Chính sách bảo hành xe điện VinFast 10 năm như thế nào?')}>
              <div className="eco-icon"><i className="mdi mdi-shield-check-outline"></i></div>
              <h3>Bảo hành 10 năm</h3>
              <p>Chính sách bảo hành xe và pin vượt trội hàng đầu thị trường ô tô toàn cầu</p>
            </div>
            <div className="eco-card" onClick={() => onOpenChat('So sánh chi phí sạc điện VinFast và chi phí xăng')}>
              <div className="eco-icon"><i className="mdi mdi-cash-multiple"></i></div>
              <h3>Tiết kiệm chi phí</h3>
              <p>Chi phí năng lượng và bảo dưỡng định kỳ tiết kiệm tới 50% so với xe xăng</p>
            </div>
            <div className="eco-card" onClick={() => onOpenChat('Dịch vụ cứu hộ 24/7 của VinFast hoạt động thế nào?')}>
              <div className="eco-icon"><i className="mdi mdi-tow-truck"></i></div>
              <h3>Cứu hộ 24/7 miễn phí</h3>
              <p>Hỗ trợ sạc lưu động và cứu hộ 24/7 xuyên suốt mọi cung đường trên toàn quốc</p>
            </div>
          </div>
        </div>
      </section>

      {/* ── Landing Footer ─────────────────────────────────────── */}
      <footer className="landing-footer">
        <div className="footer-container">
          <div className="footer-col">
            <div className="navbar-logo">
              <span className="logo-text">VINFAST</span>
            </div>
            <p className="footer-about">
              Công ty TNHH Kinh doanh Thương mại và Dịch vụ VinFast — Thành viên của Tập đoàn Vingroup.
            </p>
            <p className="footer-hotline">Tổng đài CSKH: <strong>1900 23 23 89</strong></p>
          </div>
          <div className="footer-col">
            <h4>Dòng xe điện</h4>
            <ul>
              <li><button onClick={() => onOpenChat('Tư vấn xe VF 3')}>VinFast VF 3</button></li>
              <li><button onClick={() => onOpenChat('Tư vấn xe VF 5 Plus')}>VinFast VF 5 Plus</button></li>
              <li><button onClick={() => onOpenChat('Tư vấn xe VF 6')}>VinFast VF 6</button></li>
              <li><button onClick={() => onOpenChat('Tư vấn xe VF 7')}>VinFast VF 7</button></li>
              <li><button onClick={() => onOpenChat('Tư vấn xe VF 8')}>VinFast VF 8</button></li>
              <li><button onClick={() => onOpenChat('Tư vấn xe VF 9')}>VinFast VF 9</button></li>
            </ul>
          </div>
          <div className="footer-col">
            <h4>Dịch vụ & Tiện ích</h4>
            <ul>
              <li><button onClick={() => onOpenChat('Hướng dẫn tìm trạm sạc gần nhất')}>Mạng lưới trạm sạc</button></li>
              <li><button onClick={() => onOpenChat('Chính sách thuê pin và mua đứt pin')}>Chính sách pin</button></li>
              <li><button onClick={() => onOpenChat('Quy trình đặt lịch bảo dưỡng xe VinFast')}>Dịch vụ hậu mãi</button></li>
            </ul>
          </div>
        </div>
        <div className="footer-bottom">
          <span>© 2026 VinFast. Bản quyền thuộc về VinFast Auto.</span>
        </div>
      </footer>
    </div>
  )
}
