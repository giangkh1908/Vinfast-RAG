<h1 style="color: #004b93; font-size: 32px; font-weight: 800; line-height: 1.15; margin: 0 0 18px;">Eval Logging Contract — Trust Foundation</h1>

<div style="border-top: 3px solid #004b93; margin: 0 0 28px;"></div>

<div style="background-color: #f2f6fb; border-left: 3px solid #004b93; border-radius: 0 8px 8px 0; padding: 24px 32px; margin: 0 0 32px;">

<p style="font-size: 18px; font-weight: 700; font-style: italic; line-height: 1.55; margin: 0;">Engineering cần log, export và bàn giao những gì để PM/QA có thể tự chạy evaluation và audit kết quả của lát cắt đầu tiên?</p>

</div>

<h2 style="color: #004b93; border-bottom: 2px solid #dbe4ee; padding-bottom: 8px; margin: 40px 0 18px;">Mục đích của contract này là gì?</h2>

Contract này xác định dữ liệu tối thiểu Engineering cần <span style="color: #006fbf; font-weight: 700;">log</span> lại và <span style="color: #006fbf; font-weight: 700;">export</span> ra để PM/QA có thể tự chạy evaluation, truy vết decision, retrieved evidence, answer và citation trên một build và data snapshot xác định mà không cần Engineering hỗ trợ trực tiếp.

Đây không phải Eval Plan hoặc Golden Dataset hoàn chỉnh. Mục tiêu hiện tại là bảo đảm kết quả eval có thể audit, tái lập và dùng để xác định nguyên nhân lỗi.

<h2 style="color: #004b93; border-bottom: 2px solid #dbe4ee; padding-bottom: 8px; margin: 40px 0 18px;">Engineering cần bàn giao những gì?</h2>

Trước vòng eval đầu tiên, Engineering bàn giao các đầu ra theo thứ tự ưu tiên sau:

| Deliverable | Yêu cầu / mục đích |
|---|---|
| <span style="color: #067647; background-color: #ecfdf3; font-weight: 700; padding: 2px 6px; border-radius: 4px;">Structured Request Log</span> | Ghi dữ liệu theo schema P0 ở phần 4 để PM/QA truy vết được decision, retrieved evidence, answer, citation và lỗi của từng request. |
| <span style="color: #067647; background-color: #ecfdf3; font-weight: 700; padding: 2px 6px; border-radius: 4px;">Evaluation Result Export</span> | Xuất kết quả thành JSONL và lưu riêng từng run để audit, so sánh; có thể bổ sung CSV nếu thuận tiện. |
| **Repeatable Test Runner (Optional)** | Cung cấp batch runner để PM/QA tự chạy cùng một test set trên các version khác nhau; có thể dùng UI/API theo phương án fallback ở phần 7 nếu chưa kịp triển khai. |
| **Evaluation Runbook (Optional)** | Chỉ rõ cách chạy test, tìm request log và mở retrieved evidence; có thể bàn giao bằng README hoặc tin nhắn hướng dẫn ngắn. |

Ưu tiên khả năng audit và tốc độ triển khai. Chưa cần dashboard, hệ thống chấm điểm tự động hoặc LLM-as-a-judge.

<h2 style="color: #004b93; border-bottom: 2px solid #dbe4ee; padding-bottom: 8px; margin: 40px 0 18px;">Cần tuân thủ những nguyên tắc logging nào?</h2>

1. **Ghi đúng dữ liệu thực tế:** Log có cấu trúc phải phản ánh retrieval result, answer và citation mà hệ thống thực sự đã dùng hoặc hiển thị.
2. **Truy vết và tái lập được:** Mỗi request/run phải có ID và version của build, prompt, data snapshot.
3. **Evidence audit được:** Reviewer phải đọc lại được chunk đã truy xuất và đối chiếu citation với đúng source/chunk.
4. **Không ghi dữ liệu nhạy cảm:** Loại API key, access token, credential và secret khỏi log/export.

<h2 style="color: #004b93; border-bottom: 2px solid #dbe4ee; padding-bottom: 8px; margin: 40px 0 18px;">Mỗi request cần log những field P0 nào?</h2>

Các field được phân loại thành **Bắt buộc**, **Khi áp dụng** và **Optional**.

<h5 style="color: #2f7fae; font-weight: 700; margin: 22px 0 8px;">Quy ước giá trị rỗng</h5>

- Scalar không áp dụng: `null`.
- Array không có phần tử: `[]`.
- Trạng thái chưa chạy: dùng enum `not_run` trong status field tương ứng.
- Chỉ dùng `not_applicable` khi đó là allowed value đã được định nghĩa cho field.

<h4 style="color: #004b93; background-color: #f2f6fb; border-left: 4px solid #006fbf; padding: 10px 14px; margin: 28px 0 14px;">Request và version identity</h4>

| Field | Mức yêu cầu | Mô tả |
|---|---|---|
| `schema_version` | Bắt buộc | Phiên bản schema log, bắt đầu từ `1.0`. |
| `request_id` | Bắt buộc | ID duy nhất của request. |
| `timestamp` | Bắt buộc | Thời điểm request theo ISO 8601, có timezone. |
| `run_id` | Khi chạy eval | ID chung của một lần chạy test. |
| `test_id` | Khi chạy eval | ID từ test set; `null` với traffic không thuộc eval. |
| `build_version` | Bắt buộc | Version/deployment ID hoặc Git commit. |
| `prompt_version` | Bắt buộc | ID/hash của prompt hoặc decision rules được dùng. |
| `data_snapshot_id` | Bắt buộc | ID/hash của ingestion snapshot; không chỉ ghi URL live. |
| `conversation_id` | Khi test clarification | ID liên kết các lượt trong cùng flow. |
| `turn_index` | Khi test clarification | Số thứ tự lượt, bắt đầu từ `1`. |
| `environment` | Optional | Ví dụ: `local`, `dev`, `staging`. |
| `retrieval_config_version` | Optional | ID/hash của retrieval configuration. |
| `previous_request_id` | Optional | Request trước trong clarification flow. |

Nếu chưa có hệ thống version chính thức, Engineering có thể dùng Git commit, file hash hoặc timestamped snapshot ID. Điều quan trọng là hai run có thể xác định đang khác nhau ở đâu.

<h4 style="color: #004b93; background-color: #f2f6fb; border-left: 4px solid #006fbf; padding: 10px 14px; margin: 28px 0 14px;">Input và detected context</h4>

| Field | Mức yêu cầu | Allowed values / mô tả |
|---|---|---|
| `user_query` | Bắt buộc | Nội dung người dùng gửi nguyên văn. |
| `detected_vehicle_model` | Bắt buộc | `VF 6`, `VF 8`, `unknown`, `multiple`, `out_of_scope`. |
| `detected_vehicle_version` | Bắt buộc | `Eco`, `Plus`, `all_versions`, `unknown`, `not_applicable`. |
| `detected_topic` | Bắt buộc | Topic chuẩn trong scope, `unknown` hoặc `out_of_scope`. |
| `decision` | Bắt buộc | `answer`, `clarify`, `refuse`, `out_of_scope`. |
| `reason_code` | Bắt buộc | Một primary reason trong phần 5. |

`decision` và `reason_code` phải là output có cấu trúc của pipeline/routing. Không yêu cầu reviewer suy ngược decision từ câu trả lời tự nhiên.

<h4 style="color: #004b93; background-color: #f2f6fb; border-left: 4px solid #006fbf; padding: 10px 14px; margin: 28px 0 14px;">Retrieval và evidence</h4>

| Field | Mức yêu cầu | Allowed values / mô tả |
|---|---|---|
| `retrieval_status` | Bắt buộc | `success`, `no_result`, `error`, `not_run`. |
| `retrieved_chunks` | Bắt buộc | Mảng chunk cuối cùng thực sự được truyền vào bước tạo câu trả lời; `[]` nếu không chạy hoặc không có kết quả. |
| `retrieval_query` | Optional | Query thực tế gửi tới retriever; hữu ích khi có query rewriting. |
| `requested_top_k` | Optional | Số lượng kết quả được yêu cầu. |
| `evidence_assessment` | Optional | Nhận định của pipeline để tham khảo, không phải ground truth của eval. |

<h5 style="color: #2f7fae; font-weight: 700; margin: 22px 0 8px;">Quy tắc retrieval status</h5>

- `success`: có ít nhất một phần tử trong `retrieved_chunks`.
- `no_result`: retrieval chạy thành công nhưng `retrieved_chunks = []`.
- `error`: retrieval lỗi; không được ghi thành `no_result`.
- `not_run`: decision không yêu cầu retrieval.

<h5 style="color: #2f7fae; font-weight: 700; margin: 22px 0 8px;">Schema cho mỗi retrieved chunk</h5>

| Field | Mức yêu cầu | Mô tả |
|---|---|---|
| `rank` | Bắt buộc | Thứ hạng sau filtering/reranking nếu có. |
| `chunk_id` | Bắt buộc | ID ổn định của content unit. |
| `source_id` | Bắt buộc | ID khớp với `data-source-inventory.md`. |
| `source_title` | Bắt buộc | Tên trang hoặc tài liệu. |
| `content` | Bắt buộc | Nội dung chunk mà bước tạo câu trả lời thực sự nhận được. |
| `vehicle_model` | Bắt buộc | Entity metadata của chunk. |
| `vehicle_version` | Bắt buộc | Version metadata hoặc `all_versions`. |
| `topic` | Bắt buộc | Topic metadata. |
| `approval_status` | Bắt buộc | Trạng thái nguồn tại data snapshot đang dùng. |
| `source_url` | Khi có | URL nguồn. |
| `document_name` | Với PDF | Tên tài liệu. |
| `page` | Với PDF | Số trang PDF dùng cho citation. |
| `section` | Khi có | Section heading hoặc dòng bảng. |
| `retrieval_score` | Optional | Score do retriever cung cấp. |
| `market` | Optional | Thị trường áp dụng. |
| `language` | Optional | Ngôn ngữ nguồn. |

Không cần log toàn bộ tài liệu nếu chunk đã đủ để audit. Tuy nhiên reviewer phải có cách mở lại đúng trang/section gốc khi cần.

<h4 style="color: #004b93; background-color: #f2f6fb; border-left: 4px solid #006fbf; padding: 10px 14px; margin: 28px 0 14px;">Answer và citation</h4>

| Field | Mức yêu cầu | Mô tả |
|---|---|---|
| `displayed_answer` | Bắt buộc | Chính xác nội dung được hiển thị cho người dùng. |
| `displayed_citations` | Bắt buộc | Mảng citation thực tế hiển thị; `[]` với `clarify`, `refuse`, `out_of_scope`, trừ partial answer hợp lệ. |

<h5 style="color: #2f7fae; font-weight: 700; margin: 22px 0 8px;">Schema cho mỗi displayed citation</h5>

| Field | Mức yêu cầu | Mô tả |
|---|---|---|
| `display_text` | Bắt buộc | Nội dung citation người dùng nhìn thấy. |
| `source_id` | Bắt buộc | Source được cite. |
| `chunk_ids` | Bắt buộc | Một hoặc nhiều chunk trực tiếp hỗ trợ citation. |
| `source_url` | Khi có | URL hiển thị/mở được. |
| `document_name` | Với PDF | Tên tài liệu. |
| `page` | Với PDF | Trang được cite. |
| `section` | Khi có | Section hoặc dòng bảng được cite. |
| `citation_id` | Optional | ID citation trong response. |

P0 chưa bắt buộc Engineering tự tách factual claims và tự chấm groundedness. PM/QA sẽ review thủ công bằng `displayed_answer`, `displayed_citations` và `retrieved_chunks`.

<h3 style="color: #004b93; background-color: #f2f6fb; border-left: 4px solid #006fbf; padding: 10px 14px; margin: 28px 0 14px;">4.5 Latency và error</h3>

| Field | Mức yêu cầu | Mô tả |
|---|---|---|
| `error_stage` | Khi có lỗi | `context_detection`, `retrieval`, `generation`, `citation`, `logging`, `unknown`. |
| `error_type` | Khi có lỗi | Tên exception hoặc loại lỗi chuẩn hóa. |
| `error_message` | Khi có lỗi | Nội dung đã loại secret và dữ liệu nhạy cảm. |
| `latency_total_ms` | Optional | Tổng thời gian xử lý request. |
| `latency_retrieval_ms` | Optional | Thời gian retrieval. |
| `latency_generation_ms` | Optional | Thời gian generation. |

<h2 style="color: #004b93; border-bottom: 2px solid #dbe4ee; padding-bottom: 8px; margin: 40px 0 18px;">Decision và reason code cần được ghi như thế nào?</h2>

Mỗi request phải có đúng một `decision` và một `reason_code` chính.

| Decision       | Reason code P0                 | Khi dùng                                                                      |
| -------------- | ------------------------------ | ----------------------------------------------------------------------------- |
| `answer`       | `sufficient_direct_evidence`   | Có đủ context, direct approved evidence và citation hợp lệ.                   |
| `answer`       | `partial_direct_evidence`      | Chỉ trả phần độc lập có evidence và nói rõ phần chưa thể xác nhận.            |
| `clarify`      | `missing_model`                | Thiếu VF 6/VF 8.                                                              |
| `clarify`      | `missing_version`              | Đáp án có thể khác Eco/Plus nhưng người dùng chưa nêu version.                |
| `clarify`      | `missing_topic`                | Query quá rộng hoặc chưa rõ topic.                                            |
| `clarify`      | `ambiguous_context`            | Nhiều model/topic hoặc đại từ khiến intent không đủ rõ.                       |
| `refuse`       | `insufficient_evidence`        | Không tìm thấy approved evidence trực tiếp.                                   |
| `refuse`       | `indirect_evidence`            | Retrieved content liên quan nhưng không chứng minh claim chính.               |
| `refuse`       | `invalid_source`               | Source sai phạm vi, chưa approved, hết hiệu lực hoặc thiếu metadata bắt buộc. |
| `refuse`       | `source_conflict`              | Evidence mâu thuẫn và chưa có rule phân giải.                                 |
| `refuse`       | `citation_failure`             | Không tạo được citation hợp lệ cho factual answer candidate.                  |
| `refuse`       | `system_error`                 | Retrieval, generation, citation hoặc service khác lỗi.                        |
| `out_of_scope` | `unsupported_model`            | Mẫu xe không phải VF 6/VF 8.                                                  |
| `out_of_scope` | `unsupported_comparison`       | Yêu cầu so sánh xe/phiên bản.                                                 |
| `out_of_scope` | `unsupported_recommendation`   | Yêu cầu tư vấn hoặc gợi ý xe.                                                 |
| `out_of_scope` | `unsupported_pricing_policy`   | Giá, ưu đãi, đặt cọc hoặc chính sách theo thời điểm.                          |
| `out_of_scope` | `unsupported_after_sales`      | Bảo hành, bảo dưỡng hoặc hướng dẫn sử dụng.                                   |
| `out_of_scope` | `unsupported_safety_diagnosis` | Sự cố, cảnh báo lỗi, chẩn đoán hoặc hướng dẫn sửa chữa.                       |
| `out_of_scope` | `unsupported_contact_workflow` | Hotline, showroom, lái thử hoặc gặp Sales/Support.                            |
| `out_of_scope` | `external_source_requested`    | Người dùng yêu cầu Internet, diễn đàn hoặc nguồn ngoài inventory.             |
| `out_of_scope` | `personal_data_or_transaction` | Tài khoản, VIN, lịch sử dịch vụ, giao dịch hoặc dữ liệu cá nhân.              |

Không dùng chung `other` làm reason mặc định. Nếu phát sinh tình huống mới, Engineering ghi nhận và Product xác nhận reason code trước khi thêm vào contract.

<h2 style="color: #004b93; border-bottom: 2px solid #dbe4ee; padding-bottom: 8px; margin: 40px 0 18px;">JSONL output mẫu trông như thế nào?</h2>

JSON dưới đây minh họa cấu trúc, không khóa tên class hoặc kiến trúc triển khai nội bộ:

```json
{
  "schema_version": "1.0",
  "request_id": "req_01",
  "timestamp": "2026-08-07T16:30:00+07:00",
  "run_id": "tf_baseline_001",
  "test_id": "TF-ANS-01",
  "build_version": "git_commit_or_build_id",
  "prompt_version": "prompt_hash_or_version",
  "data_snapshot_id": "vf_tf_20260807_01",
  "user_query": "VF 6 có những phiên bản nào?",
  "detected_vehicle_model": "VF 6",
  "detected_vehicle_version": "all_versions",
  "detected_topic": "phiên_bản",
  "decision": "answer",
  "reason_code": "sufficient_direct_evidence",
  "retrieval_status": "success",
  "retrieved_chunks": [
    {
      "rank": 1,
      "chunk_id": "vf6_brochure_p11_versions",
      "source_id": "vf6_brochure_or_spec_sheet_vn",
      "source_title": "VF 6 Brochure",
      "source_url": "approved_source_url",
      "document_name": "approved_document_name.pdf",
      "page": 11,
      "section": "Bảng thông số",
      "content": "Exact content received by the downstream step",
      "vehicle_model": "VF 6",
      "vehicle_version": "all_versions",
      "topic": "phiên_bản",
      "approval_status": "approved"
    }
  ],
  "displayed_answer": "Exact answer displayed to the user",
  "displayed_citations": [
    {
      "display_text": "VF 6 Brochure, trang 11, Bảng thông số",
      "source_id": "vf6_brochure_or_spec_sheet_vn",
      "chunk_ids": ["vf6_brochure_p11_versions"],
      "source_url": "approved_source_url",
      "document_name": "approved_document_name.pdf",
      "page": 11,
      "section": "Bảng thông số"
    }
  ]
}
```

<h2 style="color: #004b93; border-bottom: 2px solid #dbe4ee; padding-bottom: 8px; margin: 40px 0 18px;">Engineering cần hỗ trợ chạy test và export như thế nào?</h2>

<h4 style="color: #004b93; background-color: #f2f6fb; border-left: 4px solid #006fbf; padding: 10px 14px; margin: 28px 0 14px;">Phương án ưu tiên — Batch runner</h4>

Engineering cung cấp một command, script hoặc endpoint nhận input tối thiểu:

```csv
test_id,user_query
TF-ANS-01,VF 6 có những phiên bản nào?
TF-CL-01,Xe đi được bao xa sau một lần sạc?
```

Output là một file JSONL, mỗi dòng tương ứng một request và tuân theo schema P0.

Yêu cầu:

- Một lần chạy tạo một `run_id` duy nhất.
- Không overwrite run cũ.
- Có thể chạy lại cùng input sau khi đổi build/prompt/data.
- File output ghi rõ `run_id` và thời điểm chạy trong tên file hoặc metadata.
- Request fail vẫn phải tạo record, kèm error fields.

<h4 style="color: #004b93; background-color: #f2f6fb; border-left: 4px solid #006fbf; padding: 10px 14px; margin: 28px 0 14px;">Fallback nếu chưa kịp làm batch runner</h4>

Cho phép PM chạy từng câu qua UI hoặc API, với điều kiện:

- UI/API trả về hoặc hiển thị `request_id`.
- Có hướng dẫn export toàn bộ record theo `request_id` hoặc khoảng thời gian.
- Bản export vẫn tuân theo schema P0.
- Engineering cung cấp một ví dụ đã chạy thành công.

Không chặn bàn giao chỉ vì chưa có CSV output đẹp. JSONL audit được quan trọng hơn format trình bày.

<h2 style="color: #004b93; border-bottom: 2px solid #dbe4ee; padding-bottom: 8px; margin: 40px 0 18px;">Cần smoke test những gì trước khi bàn giao?</h2>

Engineering chạy tối thiểu các case sau để xác nhận logging hoạt động. Đây là smoke set cho instrumentation, chưa phải Golden Dataset chính thức.

| ID         | Query / tình huống                                                                       | Expected decision | Điểm cần kiểm tra trong log                                                 |
| ---------- | ---------------------------------------------------------------------------------------- | ----------------- | --------------------------------------------------------------------------- |
| `TF-SM-01` | `VF 6 có những phiên bản nào?`                                                           | `answer`          | Có retrieved chunks, direct evidence và citation liên kết về chunk.         |
| `TF-SM-02` | `Xe đi được bao xa sau một lần sạc?`                                                     | `clarify`         | `missing_model`; không factual claim; không citation.                       |
| `TF-SM-03` | `VF 8 đi được bao xa sau một lần sạc?`                                                   | `clarify`         | `missing_version`; không tự chọn Eco/Plus; không trộn NEDC/WLTP.            |
| `TF-SM-04` | `Cho tôi biết về VF 6.`                                                                  | `clarify`         | `missing_topic`; chỉ hỏi topic cần làm rõ.                                  |
| `TF-SM-05` | `So sánh VF 6 và VF 8.`                                                                  | `out_of_scope`    | `unsupported_comparison`; retrieval có thể là `not_run`; không citation.    |
| `TF-SM-06` | `Giá và ưu đãi hiện tại của VF 8 là gì?`                                                 | `out_of_scope`    | `unsupported_pricing_policy`; không đưa giá/ưu đãi.                         |
| `TF-SM-07` | Một câu hỏi Product Information trong scope nhưng data snapshot không có direct evidence | `refuse`          | `insufficient_evidence` hoặc `indirect_evidence`; không citation trang trí. |
| `TF-SM-08` | Retrieval timeout/exception được mô phỏng nếu môi trường test cho phép                   | `refuse`          | `system_error`; có `error_stage`; không ghi thành `insufficient_evidence`.  |

Ngoài ra, chạy một flow hai lượt để xác nhận liên kết conversation:

1. Người dùng: `Xe đi được bao xa sau một lần sạc?`
2. Vivu: hỏi mẫu xe.
3. Người dùng: `VF 8 Eco.`

Hai record phải có cùng `conversation_id`; record thứ hai có `turn_index = 2` và `previous_request_id` trỏ về record đầu.

<h2 style="color: #004b93; border-bottom: 2px solid #dbe4ee; padding-bottom: 8px; margin: 40px 0 18px;">Khi nào Eval Logging được xem là hoàn thành?</h2>

Phần Eval Logging chỉ được xem là bàn giao xong khi PM/QA có thể tự thực hiện tất cả các việc sau:

- [ ] Chạy một query mà không cần Engineering thao tác hộ.
- [ ] Nhận hoặc tìm được `request_id` của query đó.
- [ ] Export record thành JSONL có đủ schema P0.
- [ ] Xác định đúng build, prompt, data snapshot và retrieval config của run.
- [ ] Thấy detected model, version, topic, decision và reason code.
- [ ] Đọc được chính xác các chunk mà downstream/model đã nhận.
- [ ] Đối chiếu citation hiển thị với `source_id`, `chunk_id`, page và section.
- [ ] Phân biệt được `no_result` với retrieval/system error.
- [ ] Liên kết được hai lượt của một clarification flow.
- [ ] Chạy lại cùng input và lưu thành run mới mà không overwrite kết quả cũ.
- [ ] Không phát hiện secret hoặc dữ liệu nhạy cảm trong log/export.
- [ ] Engineering cung cấp hướng dẫn chạy/export và một output mẫu đã kiểm tra.
