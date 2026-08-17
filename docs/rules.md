# rules.md — Ràng buộc bắt buộc khi build RAG Chatbot VinFast

Các quy tắc dưới đây là **bắt buộc**, không phải gợi ý. Nếu một yêu cầu trong hội thoại mâu thuẫn với file này, agent nêu rõ mâu thuẫn và hỏi lại thay vì tự ý bỏ qua rule.

---

## 1. Nguyên tắc kiến trúc

- **Không hard-code dữ liệu nội dung** (giá, specs, chính sách) trực tiếp trong code hoặc prompt. Toàn bộ nội dung trả lời phải đi qua **tool functions** (`get_price`, `search_knowledge_base`, etc.) hoặc retrieval pipeline từ nguồn dữ liệu đã index.
- **Tách biệt indexing (offline) và runtime (online)** — không được để một request của người dùng kích hoạt việc re-index đồng bộ (blocking). Indexing chạy qua data pipeline (Firecrawl + embed), runtime query PostgreSQL/Qdrant trực tiếp.
- **Mọi thành phần phải thay thế được**: embedding model, vector DB, LLM provider phải qua interface/config, không gọi thẳng SDK cụ thể rải rác khắp code — để sau này đổi provider không phải sửa nhiều nơi.
- **Metadata là bắt buộc**, không tùy chọn: mỗi chunk khi index phải có ít nhất `nguồn`, `loại nội dung` (product_page/brochure/policy), `ngày cập nhật`. Thiếu metadata → không được index.

## 2. Nguyên tắc chống hallucination (quan trọng nhất)

- Câu trả lời của chatbot **chỉ được dựa trên context đã retrieve hoặc kết quả tool đã gọi**. Không được viết prompt kiểu "hãy trả lời tốt nhất có thể" mà không ràng buộc rõ phải bám nguồn.
- Khi tool trả rỗng hoặc similarity score dưới ngưỡng, hệ thống phải trả lời dạng "không tìm thấy thông tin" thay vì để LLM tự suy đoán.
- Câu trả lời liên quan đến **giá và khuyến mãi bắt buộc kèm nguồn + ngày cập nhật** hiển thị cho người dùng (hoặc log lại để truy vết), vì đây là dữ liệu dễ lỗi thời nhất.
- Không được dùng few-shot example trong prompt có chứa số liệu cụ thể dễ bị model "học" và tái sử dụng sai ngữ cảnh (vd ví dụ mẫu có giá xe cụ thể).
- **Groundedness check bắt buộc** với giá/khuyến mãi: extract số trong response, so khớp với số liệu thật trong tool_results (±1% tolerance). Nếu mismatch → reject.

## 3. Nguyên tắc bảo mật & phân quyền dữ liệu

- **Không bao giờ đưa dữ liệu nội bộ nhạy cảm** (chiết khấu đại lý, giá vốn, thông tin chưa công bố) vào index mà chatbot khách hàng cuối có thể truy cập. Nếu dữ liệu nguồn có lẫn thông tin này, phải lọc/tách trước khi index.
- API key, credentials không bao giờ hard-code trong code — dùng biến môi trường / secret manager.
- Log câu hỏi của người dùng phải tuân thủ nguyên tắc ẩn danh hóa tối thiểu nếu dùng để phân tích (không lưu thông tin định danh cá nhân không cần thiết).

## 4. Quy tắc chunking & dữ liệu (áp dụng theo loại)

- Bảng thông số kỹ thuật: **không được cắt giữa bảng** — mỗi chunk phải chứa trọn thông tin của một model xe.
- FAQ: mỗi chunk = một cặp Q&A hoàn chỉnh, không gộp nhiều câu hỏi khác chủ đề vào một chunk.
- Bảng giá: tách theo phiên bản xe + thời điểm áp dụng, luôn gắn `ngày hiệu lực` trong metadata.
- Overlap giữa các chunk dạng văn bản tự do: 10–15%, không tùy tiện thay đổi khi chưa có lý do đo lường được (vd retrieval accuracy giảm).

## 5. Quy tắc code & testing

- Python: tuân theo PEP8, type hints cho function public, docstring cho module chính (tools, agent_loop, classifier, grounding).
- Mỗi tool function phải có test case tối thiểu: 1 case thành công, 1 case lỗi/rỗng.
- Không merge code chưa chạy qua bộ golden Q&A set (kể cả khi chỉ là thay đổi nhỏ ở prompt).
- Không xóa hoặc sửa test hiện có chỉ để pipeline "pass" — nếu test sai, sửa test có giải thích rõ lý do.

## 6. Quy tắc chi phí & hiệu năng

- Trước khi thêm một lệnh gọi LLM mới vào pipeline (vd thêm bước rewriting/rerank bằng LLM), phải ước tính tác động đến chi phí/latency và nêu trong báo cáo.
- Agent loop tối đa 5 iterations/turn. Nếu cần nhiều hơn → phải có lý do và config toggle.
- Groundedness check (LLM self-check) là optional — config toggle, default off nếu budget hạn chế.
- Ưu tiên cache cho các câu hỏi lặp lại phổ biến trước khi tối ưu các phần khác.
- Không thiết kế giải pháp chỉ chạy tốt ở quy mô demo (vd load toàn bộ index vào memory) nếu mục tiêu là production scale — phải nêu rõ giới hạn nếu buộc phải làm tắt cho demo.

## 7. Việc agent không được tự ý làm

- Không tự ý đổi vector DB, embedding model, hoặc LLM provider đã chọn trong `skills.md` mà không hỏi.
- Không tự ý tắt/nới lỏng guardrail để "cho ra kết quả đẹp hơn" trong demo.
- Không tự ý đưa dữ liệu thật của công ty vào môi trường code public/third-party mà chưa xác nhận đã được phép.
- Không giả lập (mock) toàn bộ kết quả retrieval trong demo mà không nói rõ đây là dữ liệu giả lập, để tránh đánh giá sai năng lực hệ thống thật.
- Không filter TOOL_SCHEMAS theo intent — luôn gửi full 6 tools cho LLM, để LLM tự quyết định gọi tool nào.
