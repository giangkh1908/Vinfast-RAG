export default function ChatFooter() {
  return (
    <div id="chat_footer" className="chat_footer">
      <span className="bottom-bar-text" id="poweredByVinbase">
        Phát triển bởi
      </span>
      <a
        href="https://vinbigdata.com/"
        target="_blank"
        rel="noopener noreferrer"
        style={{ textDecoration: 'none' }}
      >
        <span className="bottom-bar-text font-bold" style={{ color: '#0040bf', marginLeft: '4px', fontWeight: 600 }}>
          Auteen
        </span>
      </a>
    </div>
  )
}
