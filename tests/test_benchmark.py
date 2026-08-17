"""Test chạy benchmark (ground-truth độc lập) làm bộ kiểm tra chính.

Nguồn sự thật: eval/benchmark/benchmark_v1.json — bộ câu hỏi + kỳ vọng viết từ
dữ liệu nguồn (KHÔNG từ hành vi code). Test này chỉ THAM CHIẾU benchmark,
không tự viết case → tránh tautology (test khắc kết quả hiện tại của code).

Chạy OFFLINE (không LLM) qua subprocess của `eval/benchmark/run_benchmark.py`;
benchmark PASS = toàn bộ case pass (case pass rate 100%).

Run: python tests/test_benchmark.py
"""
import os
import subprocess
import sys

REPO_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
PYTHON = sys.executable
BENCH = os.path.join(REPO_ROOT, "eval", "benchmark", "run_benchmark.py")


def main() -> int:
    if not os.path.exists(BENCH):
        print(f"[test_benchmark] Không tìm thấy runner: {BENCH}")
        return 1

    env = dict(os.environ)
    env.setdefault("PYTHONUTF8", "1")
    proc = subprocess.run([PYTHON, BENCH], cwd=REPO_ROOT, env=env)
    print()
    print("→ test_benchmark: benchmark offline " + ("PASS" if proc.returncode == 0 else "FAIL"))
    return proc.returncode


if __name__ == "__main__":
    sys.exit(main())
