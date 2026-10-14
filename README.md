# Đánh giá các phương pháp mã hóa SAT (AMO) cho bài toán Sudoku

Mã nguồn và dữ liệu thực nghiệm của Báo cáo BTL số 1.
- Sinh viên: Đỗ Viết Hoàng (MSSV 24021483)
- Giảng viên hướng dẫn: TS. Tô Văn Khánh

Báo cáo so sánh 5 cách mã hóa ràng buộc **At-Most-One (AMO)** khi chuyển Sudoku sang SAT:
**Binomial, Binary, Commander, Product, Sequential Counter**. Bộ giải là **Glucose3** (qua PySAT).

## Nội dung kho lưu trữ

| File | Mô tả |
|---|---|
| [`sudoku3/benchmark_v2.py`](sudoku3/benchmark_v2.py) | Chương trình thực nghiệm: sinh đề, sinh mã hóa AMO, nạp vào bộ giải, kiểm chứng nghiệm, ghi kết quả |
| [`sudoku3/results_raw.csv`](sudoku3/results_raw.csv) | Dữ liệu thô, mỗi dòng là một lượt chạy (2400 dòng) |
| [`sudoku3/results_summary.csv`](sudoku3/results_summary.csv) | Bảng tổng hợp theo từng cấu hình (80 dòng) |

## Thiết kế thực nghiệm

- Kích thước: 9x9, 16x16, 25x25, 36x36
- Tỉ lệ ô trống: 30%, 40%, 50%, 60%
- 5 mã hóa AMO x 30 seed mỗi cấu hình = **2400 lượt chạy**
- Timeout theo kích thước (tính cả thời gian sinh, nạp và giải): 30 s (N=9, 16), 120 s (N=25), 300 s (N=36)
- Mọi lời giải trả về đều được kiểm chứng (hàng, cột, khối và các ô gợi ý)
- Chạy tuần tự (`--jobs 1`) để thời gian đo không bị nhiễu

## Môi trường

- Python 3.13.11
- python-sat 1.9.dev15 (Glucose3)
- Máy chạy: Intel Core i5-1240P, 8 GB RAM, Windows

## Cài đặt

```bash
pip install python-sat
```

## Chạy lại thực nghiệm

Chạy thử nhanh (vài phút):

```bash
python sudoku3/benchmark_v2.py --preset quick
```

Cấu hình đầy đủ như trong báo cáo (N=36 có thể mất rất nhiều giờ):

```bash
python sudoku3/benchmark_v2.py --preset full --jobs 1
```

Hoặc tự chọn tham số:

```bash
python sudoku3/benchmark_v2.py --sizes 9 16 25 36 --seeds 30 --ratios 0.3 0.4 0.5 0.6 --timeouts 9:30,16:30,25:120,36:300 --jobs 1
```

Chương trình có thể chạy tiếp (resume) nếu `results_raw.csv` đã tồn tại. Chỉ tạo lại bảng tổng hợp từ dữ liệu thô:

```bash
python sudoku3/benchmark_v2.py --summary-only
```

## Các cột trong `results_raw.csv`

| Cột | Ý nghĩa |
|---|---|
| `n`, `empty_ratio`, `empty_cells`, `seed` | Kích thước, tỉ lệ ô trống, số ô trống, seed sinh đề |
| `encoding` | Mã hóa AMO |
| `timeout`, `status` | Giới hạn thời gian (s) và kết quả (`OK` hoặc `TIMEOUT`) |
| `primary`, `aux`, `clauses` | Số biến chính, số biến phụ, số mệnh đề |
| `enc_time`, `load_time`, `sol_time`, `total_time` | Thời gian sinh mã hóa, nạp vào bộ giải, giải, và tổng (s) |
| `par2` | Điểm PAR-2: bằng `total_time` nếu giải xong, bằng `2 x timeout` nếu timeout |
| `conflicts`, `decisions`, `propagations`, `restarts` | Thống kê tìm kiếm của bộ giải |
| `verified`, `error` | Kết quả kiểm chứng nghiệm và thông báo lỗi (nếu có) |

## Giấy phép

Chưa chọn giấy phép; liên hệ tác giả nếu muốn sử dụng lại.
