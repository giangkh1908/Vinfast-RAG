# Data Layer — Deliverables cho T4 (29/7)


---

## 0. Kết quả verify thực tế nguồn data (đã fetch trực tiếp)

| Nguồn | Kết quả | Tác động lên plan |
|---|---|---|
| `omapi.vinfastauto.com/fe/v1/carModel?lang=vi&country=vn` | **API JSON thật, public, không cần login** — trả đầy đủ 7 segment (CUV/SEDAN/SUV/MiniCar/E-BUS/MPV/VAN), `model_code`, `versions[]` (theo năm), thumbnail. ⚠️ `model_code` có dấu cách (`"VF 8"`, `"VF 3"`). ⚠️ Xe xăng (Fadil, Lux A2.0, Lux SA2.0, President) vẫn nằm trong API → **phải filter khi ingest**. | Không cần Playwright cho danh mục model — cron job gọi thẳng API để build `car_catalog`. Bỏ rủi ro lớn nhất. |
| `omapi.vinfastauto.com/fe/v1/menu?carModel=...` | Trả `"carModel not found"` với mọi format (`VF8`, `VF 8`, `VF%208`) | **Không còn cần crack API này** — chỉ trả link gốc cho bảo dưỡng (mục 1, hàng 11). |
| `shop.vinfastauto.com/vn_vi/dat-coc-*` (từng model) | ✅ **Static HTML**, parse được bằng `requests` thường. Giá VF3 **đã đổi** từ lần verify trước: Eco 270.75tr (giảm từ 285tr), Plus 281.2tr (giảm từ 296tr). VF9 Plus có 2 sub-variant (7 chỗ 1.529 tỷ vs ghế cơ trưởng 1.561 tỷ). Trang tổng hợp `dat-coc-o-to-dien-vinfast.html` có **đầy đủ giá + spec cơ bản cho toàn bộ dòng** (công suất, quãng đường, chiều dài cơ sở). | **Xác nhận mạnh mẽ: giá phải là Tool** — thay đổi liên tục, sai lệch vài ngày đã khác. 1 page tổng hợp đủ populate `car_pricing` + `car_specs` cơ bản. |
| `shop.vinfastauto.com/vn_vi/dat-coc-o-to-dien-vinfast.html` (trang tổng hợp) | ✅ Chứa giá + spec cho **tất cả dòng xe** (VF2 188tr, VF3 Eco/Plus, VF5 Plus 504tr, VF e34 710tr, VF6 Eco/Plus, VF7 Eco/Plus, VF8 Eco/Plus, VF9 Eco/Plus×2, VF8 Comfort 2026). Cả dòng dịch vụ (Limo Green, Herio Green, Minio Green, EC VAN, VF MPV7). | ⚠️ Cần chốt scope: chỉ tư vấn cá nhân (SUV/CUV/MiniCar) hay cả dòng dịch vụ (E-BUS/VAN/MPV)? |
| `RollingUpCost-GetInfoRolling`, `InstallmentCost-GetInstallmentsCost` (demandware) | Endpoint thật nhưng **POST, cần CSRF token** | **Trả link chính chủ**, không tự tính (mục 1, hàng 4 và 5b). |
| `vinfastauto.com/vn_vi/*` (chính sách, bảo hành, đặt lịch) | ⚠️ **Pha trộn**: `chinh-sach-ban-hang` trả **200** qua curl (FAQ hỏi-đáp, 3 trang × 10 câu), nhưng các trang khác (`chinh-sach-bao-hanh`, `ho-tro-ky-thuat`, `node/9072`, `dang-ky-lai-thu-xe-dien`) trả **403** — nội dung chính load qua JS. | `chinh-sach-ban-hang` scrape được bằng `requests` thường. Các trang còn lại **phải dùng Playwright headless**. Đây là nguồn Embed quan trọng (mục 1, hàng 5/6/9/10). |
| `om.vinfastauto.com/vi_vn/detail?car=...` (bảo dưỡng) | ⚠️ **404** qua simple GET — cần JS hoặc session | **Xác nhận đúng quyết định: chỉ trả link gốc**, không cố crawl content. |
| `vinfastauto.com/vn_vi/tim-kiem-showroom-tram-sac` | Trang thật, filter theo tỉnh/phường, kết quả load qua AJAX | **Trả link chính chủ**, không tự query geo (mục 1, hàng 7). |
| Banner trên trang chủ | `"Ưu đãi chỉ tới 31/12!"` — voucher MLTTVN3 | Xác nhận khuyến mãi có hạn → Tool (volatility), không embed. |

---

> **Phạm vi tài liệu này: chỉ Data** — phân loại dữ liệu, DB, schema, và interface contract để bàn giao cho phần Agent. Không trình bày kiến trúc/orchestration của Agent (thuộc phần khác).

---

## 0a. Full danh sách URL cần crawl / ingest

### API (Simple HTTP — requests)

| # | URL | Mục đích | → Đích | Ghi chú |
|---|---|---|---|---|
| A1 | `https://omapi.vinfastauto.com/fe/v1/carModel?lang=vi&country=vn` | Danh mục model/version | `01_thong_tin_san_pham/car_model_api.md` | API JSON public, filter bỏ xe xăng khi ingest |

### Product pages — Static HTML (requests + BeautifulSoup)

| # | URL | Model | → Đích | Ghi chú |
|---|---|---|---|---|
| P1 | `https://shop.vinfastauto.com/vn_vi/dat-coc-o-to-dien-vinfast.html` | **Tất cả** (tổng hợp) | `01_thong_tin_san_pham/dat_coc_tong_hop.md` | Primary source cho giá + spec cơ bản. Static HTML ✅ |
| P2 | `https://shop.vinfastauto.com/vn_vi/dat-coc-xe-dien-vf3.html` | VF 3 | `01_thong_tin_san_pham/vf3.md` | ✅ Đã verify |
| P3 | `https://shop.vinfastauto.com/vn_vi/dat-coc-xe-dien-vf5.html` | VF 5 | `01_thong_tin_san_pham/vf5.md` | ✅ Đã verify |
| P4 | `https://shop.vinfastauto.com/vn_vi/dat-coc-xe-dien-vf6.html` | VF 6 | `01_thong_tin_san_pham/vf6.md` | ✅ Đã verify |
| P5 | `https://shop.vinfastauto.com/vn_vi/dat-coc-xe-dien-vf7.html` | VF 7 | `01_thong_tin_san_pham/vf7.md` | ✅ Đã verify |
| P6 | `https://shop.vinfastauto.com/vn_vi/dat-coc-xe-dien-vf8.html` | VF 8 | 404 — lấy từ P1 | URL riêng trả 404, dùng trang tổng hợp |
| P7 | `https://shop.vinfastauto.com/vn_vi/dat-coc-xe-dien-vf9.html` | VF 9 | 404 — lấy từ P1 | URL riêng trả 404, dùng trang tổng hợp |
| P8 | `https://shop.vinfastauto.com/vn_vi/dat-coc-xe-dien-vf2.html` | VF 2 | 404 — lấy từ P1 | URL riêng trả 404, dùng trang tổng hợp |

### Product pages — Cần Playwright (403 Forbidden qua simple GET)

| # | URL | Model | → Đích | Ghi chú |
|---|---|---|---|---|
| PP1 | `https://vinfastauto.com/vn_vi/dat-coc-xe-vf2` | VF 2 | `01_thong_tin_san_pham/vf2.md` | 403, cần Playwright |
| PP2 | `https://vinfastauto.com/vn_vi/dat-coc-xe-vf-mpv7` | VF MPV7 | `01_thong_tin_san_pham/vf_mpv7.md` | 403, cần Playwright |
| PP3 | `https://vinfastauto.com/vn_vi/dat-coc-xe-vf8-the-all-new-2026` | VF 8 2026 | `01_thong_tin_san_pham/vf8_2026.md` | 403, cần Playwright |

### Policy & hướng dẫn — Crawl được bằng curl (FAQ)

| # | URL | Nội dung | HTTP | Cấu trúc | → Đích |
|---|---|---|---|---|---|
| PL1 | `https://vinfastauto.com/vn_vi/chinh-sach-ban-hang?page=0` đến `?page=2` | Chính sách bán hàng (FAQ) | ✅ 200 | **FAQ hỏi-đáp**, 3 trang × 10 câu = ~30 câu | `04_ho_tro_mua_xe/chinh_sach_ban_hang.md` |
| PL2 | `https://vinfastauto.com/vn_vi/chinh-sach-bao-hanh` | Chính sách bảo hành | ⚠️ 403 | HTML trả về chỉ có nav/footer, nội dung chính load qua JS | `05_chinh_sach_dich_vu/chinh_sach_bao_hanh.md` — **cần Playwright** |

### Policy & hướng dẫn — Cần Playwright (403, nội dung load qua JS)

| # | URL | Nội dung | → Đích | Ghi chú |
|---|---|---|---|---|
| PP1 | `https://vinfastauto.com/vn_vi/chinh-sach-bao-hanh` | Chính sách bảo hành | `05_chinh_sach_dich_vu/chinh_sach_bao_hanh.md` | 403, nội dung chính load qua JS |
| PP2 | `https://vinfastauto.com/vn_vi/ho-tro-ky-thuat` | Hỗ trợ kỹ thuật | `05_chinh_sach_dich_vu/ho_tro_ky_thuat.md` | 403 |
| PP3 | `https://vinfastauto.com/vn_vi/node/9072` | ⚠️ Hướng dẫn đặt lịch bảo dưỡng (mis-scrape) | — | 403 — node/9072 thực chất là trang "đăng ký lái thử xe máy điện", KHÔNG phải đặt lịch bảo dưỡng. URL đúng chưa xác nhận → out-of-scope (xem §9) |
| PP4 | `https://vinfastauto.com/vn_vi/dang-ky-lai-thu-xe-dien` | Đăng ký lái thử | `09_dat_lich_lai_thu/huong_dan_dat_lich.md` | 403 |

### Brochure PDF (tải về, extract bằng PyMuPDF/pdfplumber)

| # | URL | Model | → Đích | Ghi chú |
|---|---|---|---|---|
| B1 | `https://static-cms-prod.vinfastauto.com/brochure_vf_2.pdf` | VF 2 | `02_thong_so_ky_thuat/vf2_brochure.md` | 1.1 MB, 2 trang |
| B2 | `https://storage.googleapis.com/vinfast-data-01/brochure/09042026/VFVN_VF%205_Brochure%20B%E1%BA%A3n%20s%E1%BB%ADa%20290126_1333PM.pdf` | VF 5 | `02_thong_so_ky_thuat/vf5_brochure.md` | 1.8 MB |
| B3 | `https://storage.googleapis.com/vinfast-data-01/brochure/14052026/VF%206_Brochure_Final_130526%20(12AM)_compressed.pdf` | VF 6 | `02_thong_so_ky_thuat/vf6_brochure.md` | >10 MB |
| B4 | `https://storage.googleapis.com/vinfast-data-01/brochure/VF8_Brochure_03022026.pdf` | VF 8 | `02_thong_so_ky_thuat/vf8_brochure.md` | |
| B5 | `https://static-cms-prod.vinfastauto.com/brochure/26052026/VF%208%20The%20he%20moi_Brochure_final%2020.05.pdf` | VF 8 2026 | `02_thong_so_ky_thuat/vf8_2026_brochure.md` | |
| B6 | `https://storage.googleapis.com/vinfast-data-01/brochure/VF%209_%20Brochure.pdf` | VF 9 | `02_thong_so_ky_thuat/vf9_brochure.md` | 2.5 MB |

> ⚠️ **Thiếu PDF cho: VF 3, VF 7, VF e34, VF MPV7** — data cho các xe này chỉ có từ landing page + API (mỏng hơn). Nếu user cung cấp thêm PDF, thêm vào bảng trên.

### Bảo dưỡng — Không crawl, chỉ trả link gốc

| # | URL pattern | Mục đích | → Đích | Ghi chú |
|---|---|---|---|---|
| M1 | `https://om.vinfastauto.com/vi_vn/detail?car={car}&year={year}&lv1={lv1}&lv2={lv2}&lv3={lv3}` | Bảo dưỡng từng model | `08_dat_lich_bao_duong/maintenance_links.md` | Trang **toàn ảnh** → RAG **bỏ qua nội dung ảnh**, chỉ trả thẳng link gốc cho user. 7 xe (VF3/VF5/VF6/VF7/VF8/VF9/VF MPV 7), mỗi xe liệt kê đủ các năm trong year_range (~24 link), nằm gọn trong 1 file `maintenance_links.md` — xem file đó, không crawl |

> **Clean data:** ~24 link (7 xe × đủ năm: VF3/VF5/VF6/VF7/VF8/VF9/VF MPV 7) lưu trong 1 file `08_dat_lich_bao_duong/maintenance_links.md`. Link năm mới nhất đã verify; link năm cũ = đổi `year=` (cùng lv1/lv2/lv3 cố định theo xe). VF 2 và VF 8 thế hệ mới chưa có link trên trang gốc → tool trả empty. Không scraper, không embed nội dung (trang toàn ảnh). Tool `get_maintenance_link(car_model, year)` tra link theo (xe, năm) rồi trả cho user.

### Utility links — Hardcode, không crawl

| # | URL | Loại | → Đích | Ghi chú |
|---|---|---|---|---|
| U1 | `https://shop.vinfastauto.com/vn_vi/dự-toán-chi-phí-lăn-bánh.html` | Dự toán chi phí lăn bánh | `03_chi_phi_lan_banh/utility_links.md` | Công cụ tính lăn bánh chính chủ |
| U2 | `https://shop.vinfastauto.com/vn_vi/dự-toán-trả-góp.html` | Dự toán trả góp | `04_ho_tro_mua_xe/utility_links.md` | Công cụ tính trả góp chính chủ |
| U3 | `https://shop.vinfastauto.com/vn_vi/thẩm-định-vay.html` | Thẩm định vay | `04_ho_tro_mua_xe/utility_links.md` | Thẩm định vay vốn |
| U4 | `https://vinfastauto.com/vn_vi/tim-kiem-showroom-tram-sac` | Tìm Showroom & Trạm sạc | `06_showroom_tram_sac/utility_links.md` | Filter theo tỉnh/phường |
| U5 | `https://vinfastauto.com/vn_vi/node/9072` | Đặt lịch bảo dưỡng | — | ⚠️ node/9072 mis-scrape (thực chất: lái thử xe máy điện) — URL đặt lịch bảo dưỡng đúng chưa xác nhận, out-of-scope |
| U6 | `https://vinfastauto.com/vn_vi/dang-ky-lai-thu-xe-dien` | Đăng ký lái thử | `09_dat_lich_lai_thu/utility_links.md` | Form đăng ký lái thử |

### Khuyến mãi — Chưa có nguồn cố định

| # | URL | Mục đích | → Đích | Ghi chú |
|---|---|---|---|---|
| K1 | *(chưa có)* | Khuyến mãi/ưu đãi | `07_khuyen_mai_uu_dai/promotions.md` | Cần Product cung cấp URL hoặc xác nhận out-of-scope cho bản đầu |

---

## 1. Phân loại dữ liệu — Embed vs Tool

| # | Đầu mục | Embed / Tool | Lý do |
|---|---|---|---|
| 1 | Thông tin sản phẩm (mô tả dòng xe, phân khúc) | **Embed** | Text mô tả ổn định, cần semantic search |
| 1b | Danh mục model/version hợp lệ | **Tool** (`list_available_models`) | Precision-critical — không để LLM tự bịa tên version không tồn tại |
| 2 | Thông số kỹ thuật (brochure PDF: nội thất, ngoại thất, an toàn, công nghệ) | **Embed** | Nội dung mô tả dài, ổn định qua thời gian |
| 3 | Giá bán, các phiên bản | **Tool** (`get_price`) | Số liệu, hay đổi, sai là mất uy tín |
| 4 | Chi phí lăn bánh | **Tool** (`get_onroad_cost_link` — trả link, KHÔNG tự tính) | Công thức thuế trước bạ/phí đăng ký theo tỉnh dễ sai, VinFast đã có sẵn công cụ dự toán chính chủ — trả link để user tự nhập, tránh rủi ro tính sai số tiền |
| 5 | Hỗ trợ mua xe — quy trình vay/đặt cọc | **Embed** | Quy trình tĩnh |
| 5b | Hỗ trợ mua xe — tính trả góp | **Tool** (`get_loan_estimate_link` — trả link, KHÔNG tự tính) | Cùng lý do #4 — VinFast đã có trang dự toán trả góp + thẩm định vay riêng, dùng lại thay vì tự viết công thức |
| 6 | Chính sách bảo hành/bảo dưỡng/hỗ trợ kỹ thuật | **Embed** | Policy tĩnh, RAG chuẩn xử lý tốt |
| 7 | Showroom & trạm sạc | **Tool** (`get_showroom_charging_link` — trả link, KHÔNG tự query geo) | Trang tìm kiếm chính chủ đã filter theo tỉnh/phường + loại trạm rất tốt — không cần tự crawl/xây bảng lat-lng riêng, tránh data lệch/outdate |
| 8 | Khuyến mãi/ưu đãi | **Tool** (`get_active_promotions`) | Volatility cao, có ngày hết hạn |
| 9 | Hướng dẫn đặt lịch bảo dưỡng/sửa chữa | **Embed** (hướng dẫn) + **Tool** (`get_booking_link`) | Hướng dẫn tĩnh, nhưng link/deep-link đặt lịch cần chính xác tuyệt đối |
| 10 | Hướng dẫn đặt lịch lái thử | Giống #9 | — |
| 11 | Bảo dưỡng theo model | **Tool** (`get_maintenance_link` — trả link, KHÔNG trả content) | Trang gốc `om.vinfastauto.com` toàn ảnh (chuỗi bước gắn chú thích vị trí: mũi tên, khoanh vùng) — RAG/VLM caption sẽ làm mất thông tin quan trọng + rủi ro an toàn nếu tóm tắt sai bước. Quyết định: không crawl/embed, trả thẳng link gốc cho user tự xem. ~24 link (7 xe × đủ năm: VF3/VF5/VF6/VF7/VF8/VF9/VF MPV 7) hardcode trong `08_dat_lich_bao_duong/maintenance_links.md` |

---

## 2. Database Stack (cloud, dùng chung cho cả nhóm)

| Loại | Lựa chọn | Lý do |
|---|---|---|
| Vector DB | **Qdrant Cloud** (free tier) | Đã dùng quen trong `RAG-Pipeline-WikiVN` (hybrid BM25+vector), giữ nhất quán stack, tránh học lại tool mới trong 2 ngày |
| Structured DB | **PostgreSQL trên Railway** (free tier / $5 plan) | Team đã có sẵn, không cần setup thêm. Dùng `psycopg2` hoặc `SQLAlchemy` kết nối bình thường. Share connection string qua `.env`. Dùng `pgAdmin` hoặc DBeaver nếu cần UI xem data. |

---

## 3. Interface Contract (Data bàn giao cho Agent)

> Data chỉ định nghĩa input/output của từng tool — việc gọi tool nào, khi nào, theo logic gì là do phần Agent quyết định.

```python
search_knowledge_base(query: str, filter_model: str = None) -> list[Chunk]
# RAG search trên toàn bộ embed corpus (mục 4)

list_available_models(segment: str = None) -> list[{model_code, model_name, segment, versions[]}]
# Chống hallucination tên xe/phiên bản

get_price(model_code: str, version: str) -> {price_vnd, effective_date, source_url}

get_specs(model_code: str, version: str = None) -> list[{spec_key, spec_value, spec_unit, version_name}]
# Trả thông số kỹ thuật chính xác từ bảng car_specs. Ví dụ: get_specs("VF 8", "Eco") → [{cong_suat_kw: "150", ...}]
# Tool này cần vì embed text phẳng dễ bị LLM bẻ cong số — bảng thông số phải là structured data

get_onroad_cost_link(model_code: str = None) -> {url: str}
# Trả link trang "Dự toán chi phí lăn bánh" chính chủ — KHÔNG tự tính, tránh sai số thuế/phí theo tỉnh

get_loan_estimate_link() -> {url: str}
# Trả link trang "Dự toán vay trả góp" / "Thẩm định vay" chính chủ — KHÔNG tự tính

get_showroom_charging_link(province: str = None) -> {url: str}
# Trả link trang "Tìm Showroom & Trạm sạc" chính chủ — KHÔNG tự query geo/lat-lng

get_active_promotions(model_code: str = None) -> list[{title, description, start_date, end_date, source_url}]

get_maintenance_link(car_model: str, year: int = None) -> {source_url: str}
# Tra link bảo dưỡng theo (xe, năm) từ ~24 link hardcode trong 08_dat_lich_bao_duong/maintenance_links.md
# (7 xe × đủ năm: VF3/VF5/VF6/VF7/VF8/VF9/VF MPV 7). car_model nhận dạng CATALOG model_code ("VF 5"). Chỉ trả link gốc —
# KHÔNG trả nội dung/ảnh (trang gốc toàn ảnh, xem lý do mục 1, hàng 11). year: tra đúng năm nếu có trong
# file; user không cho year hoặc year không có → fallback năm mới nhất của xe. Model không có link
# (VF 2, VF 8 thế hệ mới) → trả empty, agent gợi ý liên hệ showroom.

get_booking_link(type: Literal["maintenance","test_drive"], model_code: str = None) -> {url, steps[]}
```

---

## 4. Embed Corpus (dữ liệu ít/không đổi — chốt danh sách nguồn)

**Đưa vào embed:**

| # | Nguồn | Cách scrape | Ghi chú chunking |
|---|---|---|---|
| 4.1 | Text mô tả sản phẩm từ 9 landing page (`shop.vinfastauto.com/vn_vi/dat-coc-*`) | `requests` + BeautifulSoup — **static HTML, không cần Playwright** | **Loại bỏ phần giá** trước khi chunk. Chunk theo từng model, giữ metadata `model_code` |
| 4.2 | Text thông số kỹ thuật từ 6 brochure PDF | Tải PDF + PyMuPDF/pdfplumber extract | **Loại bỏ bảng giá nếu có**. Bảng thông số dạng 2 cột (nhãn↔giá trị) phải extract có cấu trúc → lưu vào `car_specs` (Tool), KHÔNG embed thẳng text phẳng |
| 4.3 | Trang chính sách bán hàng / bảo hành / hỗ trợ kỹ thuật (`vinfastauto.com/vn_vi/*`) | ⚠️ **Cần Playwright headless** — trang trả 403 qua simple GET | Chunk theo heading block, strip nav/footer boilerplate trước |
| 4.4 | Hướng dẫn đặt lịch bảo dưỡng + lái thử (phần quy trình) | ⚠️ **Cần Playwright** — nằm trên `vinfastauto.com` | Lấy phần quy trình tĩnh, không phải slot thời gian thật |

**Không đưa vào embed** (đẩy hết qua Tool — mục 3): giá bán, khuyến mãi, showroom/trạm sạc, chi phí lăn bánh, **bảo dưỡng theo model** (trang gốc toàn ảnh — chỉ trả link gốc, xem mục 1 hàng 11).

### Nguồn cần Playwright vs Simple HTTP

| Nguồn | Phương pháp | Lý do |
|---|---|---|
| `omapi.vinfastauto.com/fe/v1/carModel` | Simple HTTP (requests) | API JSON public |
| `shop.vinfastauto.com/vn_vi/dat-coc-*` | Simple HTTP (requests + BeautifulSoup) | Static HTML, giá + spec parse trực tiếp |
| `vinfastauto.com/vn_vi/chinh-sach-ban-hang` | **Simple HTTP** (requests + BeautifulSoup) | ✅ Trả 200, FAQ hỏi-đáp, 3 trang × 10 câu |
| `vinfastauto.com/vn_vi/chinh-sach-bao-hanh` | **Playwright headless** | 403, nội dung chính load qua JS |
| `vinfastauto.com/vn_vi/ho-tro-ky-thuat` | **Playwright headless** | 403 |
| `vinfastauto.com/vn_vi/node/9072` (đặt lịch bảo dưỡng) | **Playwright headless** | 403 |
| `vinfastauto.com/vn_vi/dang-ky-lai-thu-xe-dien` | **Playwright headless** | 403 |
| `om.vinfastauto.com/vi_vn/detail?car=...` (bảo dưỡng) | **Không scrape** — chỉ trả link | 404 qua simple GET, quyết định chỉ trả URL gốc |

---

## 4a. Cấu trúc thư mục data — theo 9 mục nội dung

```
data/
│
├── 01_thong_tin_san_pham/          ← Thông tin sản phẩm: dòng xe, phân khúc, giá, phiên bản
│   ├── car_model_api.md            ← Danh mục model/version từ API (Embed + Tool)
│   ├── dat_coc_tong_hop.md        ← Trang tổng hợp giá + spec cơ bản toàn bộ dòng (Tool: giá→car_pricing, spec→car_specs)
│   ├── vf3.md                      ← VF3 riêng: mô tả + giá + spec (Embed mô tả, Tool giá/spec)
│   ├── vf5.md
│   ├── vf6.md
│   ├── vf7.md
│   ├── vf8.md                      ← VF8: từ trang tổng hợp (URL riêng 404)
│   ├── vf9.md                      ← VF9: từ trang tổng hợp (URL riêng 404)
│   ├── vf2.md                      ← ⚠️ Cần Playwright (403)
│   ├── vf_mpv7.md                  ← ⚠️ Cần Playwright (403)
│   ├── vf8_2026.md                 ← ⚠️ Cần Playwright (403)
│   ├── vf_e34.md                   ← VF e34: từ trang tổng hợp (URL riêng 404)
│   └── dong_dich_vu.md             ← Limo Green, Herio Green, Minio Green, EC VAN, VF MPV7 (chỉ spec, chưa có giá)
│
├── 02_thong_so_ky_thuat/           ← Thông số KT: nội thất, ngoại thất, an toàn, công nghệ
│   ├── vf2_brochure.md             ← PDF → extract text marketing (Embed) + bảng thông số (→ car_specs)
│   ├── vf5_brochure.md
│   ├── vf6_brochure.md
│   ├── vf8_brochure.md
│   ├── vf8_2026_brochure.md
│   ├── vf9_brochure.md
│   ├── vf3_specs.md                ← ⚠️ Không có PDF → lấy từ landing page + API
│   ├── vf7_specs.md                ← ⚠️ Không có PDF → lấy từ landing page + API
│   ├── vf_e34_specs.md             ← ⚠️ Không có PDF → lấy từ landing page + API
│   └── vf_mpv7_specs.md            ← ⚠️ Không có PDF → lấy từ API
│   # ⚠️ Thiếu PDF: VF3, VF7, VF e34, VF MPV7 → data chỉ từ landing page + API (mỏng hơn)
│
├── 03_chi_phi_lan_banh/            ← Chi phí lăn bánh: link dự toán chính chủ
│   └── utility_links.md            ← Hardcode: link dự toán chi phí lăn bánh + công thức thuế (Tool)
│
├── 04_ho_tro_mua_xe/              ← Hỗ trợ mua xe: vay vốn, đặt cọc, giao xe
│   ├── chinh_sach_ban_hang.md      ← FAQ 3 trang × 10 câu, crawl bằng requests ✅ (Embed)
│   ├── utility_links.md            ← Hardcode: link dự toán trả góp + thẩm định vay (Tool)
│   └── dat_coc_giao_xe.md          ← ⚠️ Cần Playwright (403) — quy trình đặt cọc/giao xe (Embed)
│
├── 05_chinh_sach_dich_vu/          ← Chính sách bảo hành, bảo dưỡng, hỗ trợ kỹ thuật
│   ├── chinh_sach_bao_hanh.md      ← ⚠️ Cần Playwright (403) (Embed)
│   └── ho_tro_ky_thuat.md          ← ⚠️ Cần Playwright (403) (Embed)
│
├── 06_showroom_tram_sac/           ← Hệ thống showroom và trạm sạc
│   └── utility_links.md            ← Hardcode: link tìm showroom & trạm sạc (Tool)
│
├── 07_khuyen_mai_uu_dai/           ← Khuyến mãi và ưu đãi
│   └── promotions.md                ← Nhập tay khi có nguồn (Tool) — chưa có URL cố định
│
├── 08_dat_lich_bao_duong/          ← Hỗ trợ đặt lịch bảo dưỡng/sửa chữa
│   └── maintenance_links.md         ← ~24 link bảo dưỡng (7 xe × đủ năm), ghi rõ xe + năm (Tool: trả link gốc)
│
└── 09_dat_lich_lai_thu/            ← Hỗ trợ đặt lịch lái thử
    ├── huong_dan_dat_lich.md        ← ⚠️ Cần Playwright (403) — quy trình đăng ký (Embed)
    └── utility_links.md             ← Hardcode: link đăng ký lái thử (Tool)
```

### Mỗi file .md có cấu trúc thống nhất

```markdown
# [Tiêu đề]

## Nguồn
- **URL**: <url crawl>
- **Cách crawl**: requests | Playwright | API | hardcode
- **Ngày crawl**: YYYY-MM-DD

## Phân loại
- **Embed**: phần nào embed (text mô tả, policy, hướng dẫn)
- **Tool**: phần nào đưa vào structured DB (giá, spec, link)

## Nội dung

[nội dung đã clean, dạng markdown]
```

### Chi tiết từng thư mục

#### `01_thong_tin_san_pham/`

**car_model_api.md** — Danh mục model/version từ API
- **Nguồn**: `https://omapi.vinfastauto.com/fe/v1/carModel?lang=vi&country=vn`
- **Cách crawl**: `requests` — API JSON public
- **Phân loại**: Tool (`list_available_models`) → `car_catalog`
- **Nội dung**: JSON response gốc, filter bỏ xe xăng (Fadil, Lux A2.0, Lux SA2.0, President). `model_code` có dấu cách (`"VF 8"`)

**dat_coc_tong_hop.md** — Trang tổng hợp toàn bộ dòng xe
- **Nguồn**: `https://shop.vinfastauto.com/vn_vi/dat-coc-o-to-dien-vinfast.html`
- **Cách crawl**: `requests` + BeautifulSoup — static HTML ✅
- **Phân loại**: Tool (giá → `car_pricing`, spec cơ bản → `car_specs`) + Embed (mô tả sản phẩm, strip giá trước khi embed)
- **Nội dung**: Giá niêm yết + giá ưu đãi + spec cơ bản (công suất, quãng đường, chiều dài cơ sở) cho tất cả dòng xe cá nhân + dịch vụ

**vf3.md, vf5.md, vf6.md, vf7.md** — Trang riêng từng model
- **Nguồn**: `shop.vinfastauto.com/vn_vi/dat-coc-xe-dien-vf*.html`
- **Cách crawl**: `requests` + BeautifulSoup — static HTML ✅
- **Phân loại**: Tool (giá, spec) + Embed (mô tả sản phẩm, bảo hành, màu sắc — strip giá)
- **Nội dung**: Mô tả chi tiết từng model + giá + spec. Giá strip trước khi embed.

**vf2.md, vf_mpv7.md, vf8_2026.md** — Trang cần Playwright
- **Nguồn**: `vinfastauto.com/vn_vi/dat-coc-xe-*`
- **Cách crawl**: ⚠️ Playwright headless (403 qua simple GET)
- **Phân loại**: giống vf3.md

**vf8.md, vf9.md, vf_e34.md** — Không có URL riêng (404)
- **Nguồn**: lấy từ trang tổng hợp + API
- **Phân loại**: giống vf3.md

**dong_dich_vu.md** — Dòng xe dịch vụ (Herio Green, Minio Green, Limo Green, VF MPV7, EC VAN)
- **Nguồn**: trang tổng hợp + API
- **Ghi chú**: chỉ có spec, chưa có giá niêm yết. Cần chốt scope.

---

#### `02_thong_so_ky_thuat/`

**vf*_brochure.md** — PDF brochure, extract thành 2 phần:
1. **Phần marketing** (trang 1-16): text mô tả nội thất, ngoại thất, an toàn, công nghệ → **Embed** (strip disclaimer lặp, strip bảng giá)
2. **Bảng thông số** (trang 17+): extract có cấu trúc → **Tool** (`car_specs`), KHÔNG embed thẳng text phẳng

⚠️ **Không bao giờ embed bảng thông số dạng text phẳng** — LLM sẽ bẻ cong số. Bảng thông số → extract có cấu trúc → `car_specs` (Tool).

**vf3_specs.md, vf7_specs.md, vf_e34_specs.md, vf_mpv7_specs.md** — Không có PDF
- **Nguồn**: landing page riêng + API carModel + trang tổng hợp
- **Phân loại**: Tool (`car_specs`)
- **Ghi chú**: data mỏng hơn so với brochure, chỉ có spec cơ bản

---

#### `03_chi_phi_lan_banh/`

**utility_links.md** — Hardcode
- **Nguồn**: hardcode
- **Phân loại**: Tool (`get_onroad_cost_link`) → trả link VinFast chính chủ, KHÔNG tự tính
- **Nội dung**: Link dự toán chi phí lăn bánh + công thức thuế trước bạ xe điện (miễn đến 31/12/2030 theo NĐ 202/2026/NĐ-CP) + phí biển số theo tỉnh

Link: `https://shop.vinfastauto.com/vn_vi/dự-toán-chi-phí-lăn-bánh.html`

---

#### `04_ho_tro_mua_xe/`

**chinh_sach_ban_hang.md** — FAQ chính sách bán hàng
- **Nguồn**: `https://vinfastauto.com/vn_vi/chinh-sach-ban-hang` (page 0-2)
- **Cách crawl**: `requests` + BeautifulSoup — ✅ trả 200, FAQ hỏi-đáp
- **Phân loại**: Embed (policy tĩnh)
- **Nội dung**: 3 trang × 10 câu hỏi-đáp về chính sách bán hàng

**utility_links.md** — Hardcode
- **Phân loại**: Tool (`get_loan_estimate_link`) → trả link VinFast chính chủ
- **Nội dung**:
  - Dự toán trả góp: `https://shop.vinfastauto.com/vn_vi/dự-toán-trả-góp.html`
  - Thẩm định vay: `https://shop.vinfastauto.com/vn_vi/thẩm-định-vay.html`

**dat_coc_giao_xe.md** — Quy trình đặt cọc/giao xe
- **Nguồn**: `vinfastauto.com/vn_vi/...` (cần xác định URL cụ thể)
- **Cách crawl**: ⚠️ cần Playwright (403)
- **Phân loại**: Embed (quy trình tĩnh)

---

#### `05_chinh_sach_dich_vu/`

**chinh_sach_bao_hanh.md** — Chính sách bảo hành
- **Nguồn**: `https://vinfastauto.com/vn_vi/chinh-sach-bao-hanh`
- **Cách crawl**: ⚠️ Playwright headless (403)
- **Phân loại**: Embed (policy tĩnh)
- **Nội dung**: Chính sách bảo hành xe mới (7 năm/160.000 km cá nhân, 3 năm/100.000 km dịch vụ), chính sách bảo hành pin (8 năm/160.000 km chủ đầu tiên), điều kiện bảo hành

**ho_tro_ky_thuat.md** — Hỗ trợ kỹ thuật
- **Nguồn**: `https://vinfastauto.com/vn_vi/ho-tro-ky-thuat`
- **Cách crawl**: ⚠️ Playwright headless (403)
- **Phân loại**: Embed (policy tĩnh)

---

#### `06_showroom_tram_sac/`

**utility_links.md** — Hardcode
- **Phân loại**: Tool (`get_showroom_charging_link`) → trả link VinFast chính chủ, KHÔNG tự query geo
- **Nội dung**: Link tìm showroom & trạm sạc: `https://vinfastauto.com/vn_vi/tim-kiem-showroom-tram-sac`

---

#### `07_khuyen_mai_uu_dai/`

**promotions.md** — Khuyến mãi
- **Nguồn**: chưa có URL cố định — cần Product cung cấp hoặc xác nhận out-of-scope cho bản đầu
- **Phân loại**: Tool (`get_active_promotions`) — volatility cao, có ngày hết hạn
- **Nội dung**: Hiện chỉ có banner "Ưu đãi chỉ tới 31/12, voucher MLTTVN3"

---

#### `08_dat_lich_bao_duong/`

**maintenance_links.md** — Link bảo dưỡng từng model theo năm
- **Nguồn**: hardcode ~24 link đã verify (28/7/2026) — 7 xe (VF3/VF5/VF6/VF7/VF8/VF9/VF MPV 7), mỗi xe liệt kê đủ các năm trong year_range
- **Phân loại**: Tool (`get_maintenance_link`) → trả link gốc, KHÔNG trả content/ảnh (trang gốc toàn ảnh)
- **Nội dung**: link dạng `https://om.vinfastauto.com/vi_vn/detail?car=...&year=...&lv1=...&lv2=...&lv3=...` — VF3/VF5/VF6/VF7/VF8/VF9/VF MPV 7. VF 2 và VF 8 thế hệ mới chưa có link trên trang gốc → tool trả empty. Link năm cũ = đổi `year=` (cùng lv1/lv2/lv3 theo xe)

---

#### `09_dat_lich_lai_thu/`

**huong_dan_dat_lich.md** — Hướng dẫn đăng ký lái thử
- **Nguồn**: `https://vinfastauto.com/vn_vi/dang-ky-lai-thu-xe-dien`
- **Cách crawl**: ⚠️ Playwright headless (403)
- **Phân loại**: Embed (quy trình tĩnh) + Tool (`get_booking_link` → trả link)

**utility_links.md** — Hardcode
- **Phân loại**: Tool (`get_booking_link`)
- **Nội dung**: Link đăng ký lái thử: `https://vinfastauto.com/vn_vi/dang-ky-lai-thu-xe-dien`

---

## 4b. Ingest Pipeline — từ raw data đến chunk sẵn sàng embed

### Flow tổng quan

```
[data/XX_mục_nội_dùng/file.md] → [Parse + Clean] → [Phân loại: Embed hoặc Tool] → [Chunk hoặc Insert DB]
                                        ↓                                              ↓
                              (strip nav/footer/boilerplate)              (metadata gắn theo từng chunk)
```

### Mẫu chunk chuẩn — mọi nguồn embed phải map về format này

```python
@dataclass
class CleanChunk:
    """Mẫu chung cho 1 chunk đã clean, sẵn sàng embed vào Qdrant."""

    # ── Nội dung ──
    text: str                    # Nội dung text đã clean, sẵn sàng embed
    source_type: Literal[
        "product_page",         # Mô tả sản phẩm từ landing page
        "brochure",             # Thông số từ brochure PDF
        "policy",               # Chính sách bảo hành/bảo dưỡng/điều khoản
        "booking_guide",        # Hướng dẫn đặt lịch
    ]

    # ── Metadata (để filter khi search) ──
    model_code: str | None       # "VF 8", "VF 3"... None nếu không gắn model cụ thể (policy)
    section: str | None          # "ngoai_that", "noi_that", "an_toan", "cong_nghe"... None nếu không phải brochure
    source_url: str              # URL gốc để trích dẫn
    last_updated: date           # Ngày ingest/crawl
```

### Quy trình clean cho từng nguồn

#### 4b.1 — Product pages (`01_thong_tin_san_pham/*.md`)

```
Pattern 1: shop.vinfastauto.com/vn_vi/dat-coc-xe-dien-*.html  (VF3, VF5, VF6, VF7)
           → Static HTML, requests + BeautifulSoup là đủ ✅

Pattern 2: vinfastauto.com/vn_vi/dat-coc-xe-*                  (VF2, VF MPV7, VF8 2026)
           → 403 Forbidden qua simple GET, cần Playwright ⚠️

Trang tổng hợp: shop.vinfastauto.com/vn_vi/dat-coc-o-to-dien-vinfast.html
           → Static HTML, có đầy đủ giá + spec toàn bộ dòng ✅ (dùng làm primary source)

Raw HTML (1 page/model)
  │
  ├─ Strip: nav, footer, cookie banner, script, style, SVG
  ├─ Strip: toàn bộ phần GIÁ (card giá, nút "Đặt cọc", badge ưu đãi, giá ưu đãi)
  ├─ Extract: phần mô tả model (text giới thiệu, tính năng nổi bật, triết lý thiết kế)
  ├─ Extract: phần spec cơ bản (công suất, quãng đường, kích thước, dung lượng pin)
  │     → lưu riêng vào car_specs (Tool), KHÔNG embed
  ├─ Extract: giá niêm yết + giá ưu đãi + phí pin + phí màu
  │     → lưu riêng vào car_pricing (Tool), KHÔNG embed
  ├─ Extract: thông tin bảo hành (7 năm/160.000 km, 8 năm pin cho owner đầu tiên...)
  │     → lưu vào CleanChunk source_type="product_page" (embed được)
  │
  ▼
  CleanChunk(
    text="<mô tả model + tính năng + bảo hành, ĐÃ strip giá>",
    source_type="product_page",
    model_code="VF 7",
    section=None,
    source_url="https://shop.vinfastauto.com/vn_vi/dat-coc-xe-dien-vf7.html",
    last_updated=date.today()
  )
```

**Chunking strategy:** 1 model = 1 chunk (nếu text < ~1000 token) HOẶC split theo section heading nếu dài. KHÔNG chunk theo fixed character count — tách theo section ngữ nghĩa.

#### 4b.2 — Brochure PDF (`02_thong_so_ky_thuat/*_brochure.md`)

```
Raw PDF (6 file)
  │
  ├─ PyMuPDF/pdfplumber extract page-by-page
  │     ├─ Page 1-16 (marketing): prose + hình minh họa
  │     │     → strip disclaimer lặp (regex: "Hình ảnh mang tính chất minh họa...")
  │     │     → strip bảng giá nếu có
  │     │     → chunk theo heading/section
  │     │
  │     └─ Page 17+ (bảng thông số): dạng bảng 2 cột
  │           → extract có cấu trúc: cặp (label, value) theo vị trí
  │           → lưu vào car_specs (Tool), KHÔNG embed
  │
  ▼
  CleanChunk(
    text="<text thông số mô tả đã strip>",
    source_type="brochure",
    model_code="VF 8",
    section="noi_that",        # nội thất / ngoại thất / an toàn / công nghệ
    source_url="https://.../VF8_Brochure.pdf",
    last_updated=date.today()
  )
```

**Chunking strategy:** Split theo section heading (Nội thất, Ngoại thất, An toàn, Công nghệ). Mỗi section = 1 chunk. Nếu 1 section dài quá 800 token → split theo sub-heading.

#### 4b.3 — Policy pages (`04_ho_tro_mua_xe/`, `05_chinh_sach_dich_vu/`)

```
Raw HTML (rendered via Playwright hoặc requests cho chinh-sach-ban-hang)
  │
  ├─ Strip: nav, footer, sidebar, cookie banner, popup
  ├─ Strip: nút CTA, form liên hệ, social share
  ├─ Chunk theo heading block (##### CHÍNH SÁCH..., ##### ĐIỀU KHOẢN...)
  │     → mỗi heading block = 1 chunk
  │
  ▼
  CleanChunk(
    text="<nội dung chính sách đã clean>",
    source_type="policy",
    model_code=None,
    section=None,
    source_url="https://vinfastauto.com/vn_vi/chinh-sach-ban-hang",
    last_updated=date.today()
  )
```

#### 4b.4 — Maintenance links (`08_dat_lich_bao_duong/maintenance_links.md`)

```
Không scrape, không embed — hardcode ~24 link (7 xe × đủ năm: VF3/VF5/VF6/VF7/VF8/VF9/VF MPV 7)
  │
  ├─ Mỗi link dạng: om.vinfastauto.com/vi_vn/detail?car=...&year=...&lv1=...&lv2=...&lv3=...
  ├─ lv1/lv2/lv3 cố định theo xe; year= chọn năm trong year_range (link cũ = đổi year=)
  ├─ Trang gốc toàn ảnh → KHÔNG tạo chunk nội dung, chỉ lưu link vào maintenance_link (Tool)
  │
  ▼
maintenance_link (Postgres): 1 row/xe-năm, {car_model, year, source_url}
CleanChunk: KHÔNG có (phần bảo dưỡng không embed)
```

#### 4b.5 — Booking guides (`08_dat_lich_bao_duong/`, `09_dat_lich_lai_thu/`)

```
Raw HTML (rendered via Playwright)
  │
  ├─ Strip: nav, footer, CTA buttons
  ├─ Extract: phần quy trình/steps (bước 1, bước 2, bước 3...)
  │
  ▼
  CleanChunk(
    text="<quy trình đặt lịch đã clean>",
    source_type="booking_guide",
    model_code=None,
    section=None,
    source_url="https://vinfastauto.com/vn_vi/node/9072",
    last_updated=date.today()
  )
```

### Tóm tắt: nguồn nào đi đâu

| Nguồn | → Thư mục | → Structured DB (Tool) | → Vector DB (Embed) | Bỏ qua |
|---|---|---|---|---|
| `carModel` API | `01_thong_tin_san_pham/` | `car_catalog` | — | Xe xăng (Fadil, Lux, President) |
| `shop.vinfastauto.com` giá + version + giá ưu đãi | `01_thong_tin_san_pham/` | `car_pricing` (price_vnd, promo_price_vnd, battery_price_vnd, color_premium_vnd) | — | — |
| `shop.vinfastauto.com` mô tả sản phẩm + bảo hành | `01_thong_tin_san_pham/` | — | `product_page` (strip giá) | Giá (strip trước khi embed) |
| `shop.vinfastauto.com` spec cơ bản | `01_thong_tin_san_pham/` | `car_specs` (cong_suat_kw, quang_duong_km, ...) | — | — |
| Brochure PDF — phần marketing | `02_thong_so_ky_thuat/` | — | `brochure` | Disclaimer lặp, bảng giá |
| Brochure PDF — bảng thông số | `02_thong_so_ky_thuat/` | `car_specs` (chi tiết hơn landing page) | — | — |
| Policy/bảo hành (vinfastauto.com) | `04_ho_tro_mua_xe/`, `05_chinh_sach_dich_vu/` | — | `policy` | Nav/footer/CTA |
| Bảo dưỡng theo model (om.vinfastauto.com) | `08_dat_lich_bao_duong/` | `maintenance_link` (link theo xe-năm) | — (trang toàn ảnh, không embed) | Nội dung ảnh |
| Booking guide (vinfastauto.com) | `08_dat_lich_bao_duong/`, `09_dat_lich_lai_thu/` | `utility_link` (URL đặt lịch) | `booking_guide` | Nav/footer/CTA |
| Khuyến mãi | `07_khuyen_mai_uu_dai/` | `promotion` | — | — |

---

## 5. Schemas

### 5.1 Vector DB — Qdrant collection `vinfast_kb`
```json
{
  "id": "uuid",
  "vector": [...],
  "payload": {
    "text": "string (chunk content)",
    "source_type": "product_page | brochure | policy | booking_guide",
    "model_code": "VF8 | null",
    "section": "dau_mo_phu_tung | null",
    "source_url": "string",
    "last_updated": "date"
  }
}
```

### 5.2 Postgres tables

```sql
car_catalog (
  model_code TEXT PRIMARY KEY,
  model_name TEXT,
  segment TEXT,
  status TEXT,
  versions JSONB,
  source_url TEXT,
  updated_at TIMESTAMP
)

car_pricing (
  id SERIAL PRIMARY KEY,
  model_code TEXT REFERENCES car_catalog,
  version_name TEXT,
  price_vnd BIGINT,               -- giá niêm yết
  promo_price_vnd BIGINT,          -- giá ưu đãi (NULL nếu không có)
  battery_included BOOLEAN DEFAULT TRUE,  -- FALSE nếu pin tính phí riêng (VF2, VF5: +80tr)
  battery_price_vnd BIGINT,        -- giá pin riêng (NULL nếu đã bao gồm)
  color_premium_vnd BIGINT,        -- phụ phí màu nâng cao (NULL nếu không có)
  effective_date DATE,
  source_url TEXT
)

car_specs (
  id SERIAL PRIMARY KEY,
  model_code TEXT REFERENCES car_catalog,
  version_name TEXT,        -- nullable nếu spec áp dụng chung mọi version
  spec_key TEXT,            -- "cong_suat_kw", "quang_duong_km", "chieu_dai_co_so_mm"...
  spec_value TEXT,          -- "150", "500", "2840" — giữ string để linh hoạt đơn vị
  spec_unit TEXT,            -- "kW", "km", "mm", "hp"...
  source_url TEXT,
  updated_at TIMESTAMP
)
-- Bảng thông số kỹ thuật extract từ brochure + landing page. Dùng cho Tool trả JSON chính xác,
-- KHÔNG embed thẳng text phẳng (dễ bị LLM bẻ cong số).

utility_link (
  id SERIAL PRIMARY KEY,
  link_type TEXT CHECK (link_type IN (
    'onroad_cost','loan_estimate','loan_appraisal',
    'showroom_charging','maintenance_booking','test_drive_booking'
  )),
  model_code TEXT,       -- nullable, một số link áp dụng chung mọi model
  url TEXT,
  updated_at TIMESTAMP
)
-- Gộp các link "trả thẳng, không tự tính/tự query" ở mục 1 (hàng 4, 5b, 7) và mục 9-10 vào 1 bảng duy nhất

promotion (
  id SERIAL PRIMARY KEY,
  model_code TEXT REFERENCES car_catalog,
  title TEXT, description TEXT,
  start_date DATE, end_date DATE,
  source_url TEXT
)

maintenance_link (
  id SERIAL PRIMARY KEY,
  car_model  TEXT,           -- catalog model_code: "VF 5", "VF 3", "VF MPV 7"...
  year       INT,            -- năm của link: 2026, 2025, 2024...
  source_url TEXT,           -- full link om.vinfastauto.com/vi_vn/detail?... (đã có sẵn lv1/lv2/lv3)
  updated_at TIMESTAMP,
  UNIQUE (car_model, year)
)
-- ~24 row (7 xe × đủ năm: VF3/VF5/VF6/VF7/VF8/VF9/VF MPV 7), hardcode từ 08_dat_lich_bao_duong/maintenance_links.md.
-- Link năm cũ = đổi year= (cùng lv1/lv2/lv3 cố định theo xe). KHÔNG scrape (trang gốc toàn ảnh).
-- Tool get_maintenance_link(car_model, year) tra source_url theo (xe, năm); year không có → fallback năm mới nhất.
```

---

## 6. Deliverables cụ thể cho T4 (29/7) — ưu tiên thực tế

### P0 — Phải có (block Agent team nếu thiếu)

- [ ] **Railway Postgres provisioned** — tạo toàn bộ bảng ở mục 5.2, share connection string cho team qua `.env`
- [ ] **Qdrant Cloud collection `vinfast_kb`** — tạo xong, index ≥ 1 nguồn thật (ưu tiên: trang tổng hợp giá/spec + policy pages) để team Agent có data test ngay
- [ ] **Scraper `shop.vinfastauto.com`** — parse giá + spec cơ bản → populate `car_pricing` + `car_specs`. ✅ Đã verify: static HTML, `requests` + BeautifulSoup là đủ. ⚠️ Cần xử lý 2 pattern URL: `shop.vinfastauto.com/vn_vi/dat-coc-xe-dien-*.html` (VF3/5/6/7) vs `vinfastauto.com/vn_vi/dat-coc-xe-*` (VF2/MPV7/VF8-2026, cần Playwright). Trang tổng hợp `dat-coc-o-to-dien-vinfast.html` có đầy đủ giá+spec toàn bộ dòng, dùng làm primary source. Lưu ý: `car_pricing` cần cả `price_vnd` (niêm yết) và `promo_price_vnd` (ưu đãi)
- [ ] **Cron job gọi `omapi.vinfastauto.com/fe/v1/carModel`** → populate `car_catalog`. ✅ Đã verify: API JSON public, chạy trực tiếp. Lưu ý: filter bỏ xe xăng (Fadil, Lux A2.0, Lux SA2.0, President) khi ingest, và chuẩn hóa `model_code` có dấu cách (`"VF 8"` không phải `"VF8"`)
- [ ] **10 tool function ở mục 3** — schema input/output final, code stub trả mock data. Đủ để team Agent wire vào và test routing
- [ ] **`utility_link`** — hardcode 1 lần các link tĩnh: dự toán chi phí lăn bánh, dự toán trả góp, thẩm định vay, tìm showroom/trạm sạc, đặt lịch bảo dưỡng, đăng ký lái thử

### P1 — Nên có (rất hữu ích nhưng không block)

- [ ] **`maintenance_link`** — hardcode ~24 link bảo dưỡng (7 xe × đủ năm: VF3/VF5/VF6/VF7/VF8/VF9/VF MPV 7) từ `08_dat_lich_bao_duong/maintenance_links.md`. KHÔNG cần scrape, KHÔNG cần crack API `menu`
- [ ] **Embed policy/hướng dẫn từ `vinfastauto.com`** — ⚠️ Cần Playwright headless vì trang trả 403 qua simple GET. Nếu không có Playwright → fallback: copy-paste thủ công nội dung policy vào file text rồi ingest
- [ ] **Brochure PDF parser** — tải 6 PDF, extract text cho embed + bảng thông số cho `car_specs`. Bảng thông số phải extract có cấu trúc (không embed thẳng text phẳng)

### P2 — Nếu còn thời gian

- [ ] **Eval set 15-20 câu hỏi mẫu** — gắn expected route (embed hay tool) để test agent routing đúng/sai
- [ ] **Cron job cập nhật giá** — chạy daily, so sánh giá mới/cũ, flag nếu lệch > 5%
- [ ] **Embed product pages riêng lẻ** (9 trang `dat-coc-*`) — mô tả chi tiết từng model, sau khi đã strip giá

---

## 7. Verified price data (verify 27/7)

> Giá từ `shop.vinfastauto.com` — **sẽ đổi**, cần cron job cập nhật.
> ⚠️ URL pattern không đồng nhất: VF3/5/6/7 dùng `shop.vinfastauto.com/vn_vi/dat-coc-xe-dien-*.html`, VF2/MPV7/VF8-2026 dùng `vinfastauto.com/vn_vi/dat-coc-xe-*` (cần Playwright).

### Dòng xe cá nhân (có giá)

| Model | Version | Giá niêm yết (VND) | Giá ưu đãi (VND) | Pin | Phí màu cao cấp | Ghi chú |
|---|---|---|---|---|---|---|
| VF 2 | Tiêu chuẩn | 188.000.000 | — | +80tr | — | Pin thuê riêng |
| VF 3 | Eco | 285.000.000 | 270.750.000 | ✅ | +8tr | |
| VF 3 | Plus | 296.000.000 | 281.200.000 | ✅ | — | |
| VF 5 | Plus | 496.000.000 | 471.200.000 | +80tr | — | Pin thuê riêng |
| VF e34 | SMART | 710.000.000 | — | ✅ | — | 1 màu Desat Silver |
| VF 6 | Eco | 664.050.000 | 613.700.000 | ✅ | — | |
| VF 6 | Plus | 699.000.000 | 646.000.000 | ✅ | — | |
| VF 7 | Eco | 740.000.000 | 703.000.000 | ✅ | — | |
| VF 7 | Plus | 830.000.000 | 788.500.000 | ✅ | — | FWD |
| VF 7 | Plus kính toàn cảnh | 850.000.000 | 807.500.000 | ✅ | — | AWD |
| VF 8 | Eco | 898.000.000 | — | ✅ | +12tr | |
| VF 8 | Plus | 1.079.000.000 | — | ✅ | +12tr | |
| VF 8 | Comfort (2026) | — | — | ✅ | — | 170 kW, 480-500 km NEDC |
| VF 9 | Eco | 1.348.000.000 | — | ✅ | — | |
| VF 9 | Plus (7 chỗ) | 1.529.000.000 | — | ✅ | +12tr | |
| VF 9 | Plus (ghế cơ trưởng) | 1.561.000.000 | — | ✅ | +12tr | |

### Dòng dịch vụ (chỉ có spec, chưa có giá niêm yết trên trang)

| Model | Mã variant | Công suất | Quãng đường NEDC | Chiều dài cơ sở | Pin thuê riêng | Ghi chú |
|---|---|---|---|---|---|---|
| Herio Green | GA1XV, GA1QV | 110 kW | 318.6-326 km | 2.514-2.611 mm | — | 2 variant khác wheelbase |
| Minio Green | TH12V | 30 kW | 210 km | 2.065 mm | — | 12+ màu |
| Limo Green | SL1VV | 150 kW | 450 km | 2.840 mm | — | |
| VF MPV 7 | SL1WV | 150 kW | 450 km | 2.840 mm | — | |
| EC VAN | TG10V, TG12V, TG11V | 30 kW | 175 km | 2.520 mm | — | 3 variant |
| Nerio Green | — | — | — | — | — | Không có spec trên trang tổng hợp |

---

## 8. carModel API — cấu trúc JSON thật (verify 27/7)

```json
{
  "success": true,
  "data": {
    "align": 0,
    "downloads": null,
    "pdf": null,
    "vehicles": [
      {"id": 3, "code_name": "CUV"},
      {"id": 4, "code_name": "SEDAN"},
      {"id": 5, "code_name": "SUV"},
      {"id": 12, "code_name": "MiniCar"},
      {"id": 13, "code_name": "E-BUS"},
      {"id": 15, "code_name": "MPV"},
      {"id": 16, "code_name": "VAN"}
    ],
    "models": {
      "SUV": [
        {
          "model_name": "VF 9",
          "model_code": "VF 9",
          "thumbnail": "https://...",
          "text_align": 0,
          "versions": ["2026", "2025", "2024", "2023"],
          "version_thumbnails": {"2026": "https://...", ...},
          "vehicle_id": 5
        },
        // ... President, Nerio Green, VF e34, LacHong900LX, Lux SA2.0, Herio Green, VF5, VF7, VF8, VF6
      ],
      "MiniCar": [
        {"model_name": "Minio Green", "model_code": "Minio Green", ...},
        {"model_name": "VF3", "model_code": "VF 3", ...}
      ],
      "CUV": [{"model_name": "Fadil", "model_code": "Fadil", ...}],
      "SEDAN": [{"model_name": "Lux A2.0", "model_code": "Lux A2.0", ...}],
      "E-BUS": [...],
      "MPV": [...],
      "VAN": [...]
    }
  }
}
```

> **Lưu ý ingest:** `model_code` dùng dấu cách (`"VF 8"` không phải `"VF8"`). Xe xăng (Fadil, Lux A2.0, Lux SA2.0, President) cần filter bỏ.

---

## 9. Open questions / risks

- ~~Phạm vi `om.vinfastauto.com`: ô tô hay cả xe máy điện~~ → **Chỉ lấy xe điện (ô tô)**: VF2, VF3, VF5, VF6, VF7, VF MPV7, VF8, VF8 The All New 2026, VF9, VF e34. **Loại bỏ hoàn toàn dòng xăng** (Fadil, Lux A2.0, Lux SA2.0, President) — đã ngừng bán, không phục vụ use case tư vấn mua xe điện.
- ⚠️ **Scope dòng xe dịch vụ**: API trả thêm EB6/EB8/EB10 (xe buýt), EC VAN, Limo Green, Herio Green, Minio Green, VF MPV7, LacHong900LX. Cần chốt: tư vấn cho cá nhân mua xe (chỉ SUV/CUV/MiniCar) hay cả dòng dịch vụ (E-BUS/VAN/MPV)?
- **Trang `vinfastauto.com/vn_vi/*` trả 403** qua simple GET — nội dung policy/bảo hành/hướng dẫn đều nằm ở đây. Đây là nguồn Embed quan trọng (mục 1, hàng 5/6/9/10). → **Cần Playwright headless** để scrape. Nếu team không có kinh nghiệm Playwright → đây là risk lớn nhất cho Embed corpus.
- **Nội dung nào chỉ tồn tại dưới dạng PDF** → xử lý chung pipeline với brochure (tải PDF, extract bằng PDF parser), bảng thông số extract có cấu trúc vào `car_specs` (Tool), không embed thẳng text phẳng.
- Nguồn data cho **khuyến mãi** chưa có URL cố định — cần Product cung cấp hoặc xác nhận out-of-scope cho bản đầu.
- ⚠️ **Giá bán thay đổi liên tục** — VF3 đã giảm 5-6% giữa 2 lần verify. Cần cron job cập nhật `car_pricing` thường xuyên (đề xuất: daily) và flag khi giá cũ lệch quá 5%.