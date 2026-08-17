import requests
import json
import re
from typing import List, Dict
from urllib.parse import urlparse

def extract_urls(text: str) -> List[str]:
    """Trích xuất tất cả các URL từ văn bản."""
    url_pattern = r'https?://[^\s\)\],]+'
    return re.findall(url_pattern, text)

def verify_urls(responses: List[Dict]) -> List[Dict]:
    """
    Kiểm tra tính hợp lệ của các URL trong danh sách câu trả lời.

    Input: List các dict chứa {'query': ..., 'response': ...}
    Output: List các dict chứa kết quả verify
    """
    results = []

    for idx, item in enumerate(responses):
        response_text = item.get('response', '')
        urls = extract_urls(response_text)

        url_status = []
        for url in urls:
            try:
                # Sử dụng HEAD request để nhanh hơn GET
                res = requests.head(url, timeout=5, allow_redirects=True)
                status = "PASS" if res.status_code == 200 else f"FAIL ({res.status_code})"
            except requests.RequestException as e:
                status = f"ERROR ({type(e).__name__})"

            url_status.append({"url": url, "status": status})

        results.append({
            "id": idx,
            "query": item.get('query', ''),
            "urls_found": len(urls),
            "details": url_status,
            "overall_url_status": "PASS" if all(u['status'] == "PASS" for u in url_status) and urls else "FAIL"
        })

    return results

if __name__ == "__main__":
    # Ví dụ dữ liệu test
    test_data = [
        {
            "query": "Giá gói A là bao nhiêu?",
            "response": "Giá gói A là 100k. Xem chi tiết tại https://google.com"
        },
        {
            "query": "Thông tin sai",
            "response": "Đây là link lỗi: https://this-is-a-fake-url-12345.com"
        }
    ]

    print("--- Đang kiểm tra URLs ---")
    final_results = verify_urls(test_data)
    print(json.dumps(final_results, indent=2, ensure_ascii=False))
