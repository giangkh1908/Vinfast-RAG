# Bộ Test Case Đánh Giá Generation & Citation của LLM

Tài liệu này định nghĩa các kịch bản kiểm thử để đánh giá chất lượng câu trả lời (Generation) và độ chính xác của nguồn trích dẫn (Citation/URL) cho hệ thống RAG.

## 1. Tiêu chí Đánh giá (Metrics)

### Quality of Answer (QoA)
- **Faithfulness (1-5):** Câu trả lời có trung thành với tài liệu không? (1: Bịa hoàn toàn, 5: Hoàn toàn khớp).
- **Relevance (1-5):** Có trả lời đúng trọng tâm câu hỏi không?
- **Completeness (1-5):** Có bỏ sót thông tin quan trọng từ context không?

### Quality of Citations (QoC)
- **Validity (Pass/Fail):** URL có truy cập được không (Status 200)?
- **Precision (1-5):** Nội dung tại URL có chứa thông tin được trích dẫn không? (1: Không liên quan, 5: Chính xác tuyệt đối).
- **Alignment (Pass/Fail):** Vị trí đặt trích dẫn trong câu có khớp với nội dung của URL không?

---

## 2. Chi tiết Test Cases

### Nhóm 1: Happy Path (Luồng chuẩn)
| ID | Scenario | Input (Query) | Context Requirement | Expected Result |
| :--- | :--- | :--- | :--- | :--- |
| TC-01 | Câu hỏi đơn giản, 1 nguồn | "Giá gói A là bao nhiêu?" | 1 tài liệu ghi rõ giá gói A. | Trả lời đúng giá, kèm 1 URL chính xác. |
| TC-02 | Câu hỏi tổng hợp, nhiều nguồn | "So sánh gói A và gói B" | Tài liệu A và tài liệu B mô tả đặc điểm. | Bảng so sánh hoặc list ý, kèm $\ge 2$ URL tương ứng. |
| TC-03 | Câu hỏi chi tiết (How/Why) | "Cách cài đặt phần mềm X?" | Tài liệu hướng dẫn từng bước. | Trả lời theo step-by-step, URL dẫn đến trang hướng dẫn. |

### Nhóm 2: Negative & Edge Cases (Luồng lỗi/Biên)
| ID | Scenario | Input (Query) | Context Requirement | Expected Result |
| :--- | :--- | :--- | :--- | :--- |
| TC-04 | Out-of-scope (Không có dữ liệu) | "Thời tiết hôm nay thế nào?" | Context không chứa thông tin thời tiết. | Từ chối trả lời/Báo không tìm thấy. KHÔNG tự bịa, KHÔNG đưa URL linh tinh. |
| TC-05 | Conflicting Information | "Ngày ra mắt sản phẩm X?" | Nguồn A nói 1/1, Nguồn B nói 1/2. | Chỉ ra sự mâu thuẫn giữa 2 nguồn. Kèm cả 2 URL. |
| TC-06 | Noise Interference | "Tính năng Y là gì?" | 1 tài liệu đúng, 4 tài liệu nói về Z. | Chỉ lấy thông tin từ tài liệu đúng. URL chỉ chứa nguồn đúng. |
| TC-07 | Vague Query | "Cho tôi biết về X" | Tài liệu X có nhiều khía cạnh (giá, tính năng, lịch sử). | Hỏi lại để làm rõ hoặc tóm tắt ngắn gọn các khía cạnh chính. |

### Nhóm 3: Citation Stress Test
| ID | Scenario | Goal | Expected Result |
| :--- | :--- | :--- | :--- |
| TC-08 | Deep Linking | Kiểm tra URL có dẫn đến section cụ thể không. | URL có dạng `.../page#section` hoặc dẫn đúng trang con thay vì trang chủ. |
| TC-09 | Hallucinated URL | Kiểm tra việc tự tạo link giả. | Click vào link $\rightarrow$ Không bị 404. |
| TC-10 | Source-Content Match | Kiểm tra sự khớp nhau giữa text và link. | Nội dung trong URL phải chứa keyword của câu trả lời. |
