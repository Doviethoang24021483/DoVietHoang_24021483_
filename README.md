# Đánh giá các phương pháp mã hóa SAT (AMO) cho bài toán Sudoku

Mã nguồn và dữ liệu thực nghiệm của Báo cáo BTL số 1.

- Sinh viên: Đỗ Viết Hoàng (MSSV 24021483)
- Giảng viên hướng dẫn: TS. Tô Văn Khánh

Báo cáo so sánh 5 cách mã hóa ràng buộc **At-Most-One (AMO)** khi chuyển Sudoku sang SAT:
**Binomial, Binary, Commander, Product, Sequential Counter**. Bộ giải là **Glucose3** (qua PySAT).

## Nội dung kho lưu trữ

| File | Mô tả |
|---|---|
| [`sudoku3/benchmark_v2.py`](sudoku3/benchmark_v2.py) | Chương trình thực nghiệm: sinh đề, sinh mã hóa AMO, nạp vào bộ giải, kiểm chứng nghiệm, ghi kết quả; in bảng tổng hợp nhanh (có Fisher–Holm) |
| [`sudoku3/analyze.py`](sudoku3/analyze.py) | Script phân tích: đọc dữ liệu thô, tính Friedman, Wilcoxon–Holm, Fisher–Holm, bootstrap, độ nhạy PAR-k, regret; sinh lại các bảng, hình của Chương 4 và in các con số dùng trong văn xuôi |
| [`sudoku3/results_raw.csv`](sudoku3/results_raw.csv) | Dữ liệu thô, mỗi dòng là một lượt chạy (2400 dòng) |
| [`sudoku3/results_summary.csv`](sudoku3/results_summary.csv) | Bảng tổng hợp nhanh theo từng cấu hình (80 dòng), không gồm các kiểm định |
| [`sudoku3/requirements.txt`](sudoku3/requirements.txt) | Các thư viện Python cần cài (đã ghim đúng phiên bản của báo cáo) |

Thư mục `sudoku3/analysis_out/` do `analyze.py` sinh ra mỗi lần chạy (có thể xóa và tạo lại bất cứ lúc nào, đã nằm trong `.gitignore`).

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
- NumPy 2.4.3, pandas 3.0.1, SciPy 1.17.1, Matplotlib 3.10.8
- Máy chạy: Intel Core i5-1240P, 8 GB RAM, Windows 11

## Cài đặt

```bash
cd sudoku3
pip install -r requirements.txt
```

## Chạy lại thực nghiệm

Chạy thử nhanh (vài phút):

```bash
python benchmark_v2.py --preset quick --out quick_raw.csv --summary-out quick_summary.csv
```

Cấu hình đầy đủ như trong báo cáo (N=36 có thể mất rất nhiều giờ):

```bash
python benchmark_v2.py --preset full --jobs 1
```

Hoặc tự chọn tham số:

```bash
python benchmark_v2.py --sizes 9 16 25 36 --seeds 30 --ratios 0.3 0.4 0.5 0.6 --timeouts 9:30,16:30,25:120,36:300 --jobs 1
```

Chương trình có thể chạy tiếp (resume) nếu file `--out` đã tồn tại: các lượt `OK`/`TIMEOUT` có cùng (N, tỉ lệ, mã hóa, seed, timeout) được bỏ qua, còn các dòng `ERROR` sẽ được chạy lại. Vì vậy khi thử nhanh hãy dùng file `--out` riêng để không ghi đè `results_raw.csv`. Chỉ tạo lại bảng tổng hợp nhanh từ dữ liệu thô:

```bash
python benchmark_v2.py --summary-only
```

### Thực nghiệm mở rộng (tùy chọn)

Quét thêm tỉ lệ ô trống để xác định đỉnh độ khó; luôn dùng `--out` riêng:

```bash
# Rẻ hơn: N=25, ρ cao hơn (đỉnh độ khó của N=25 chưa thấy ở ρ ≤ 60%)
python benchmark_v2.py --sizes 25 --ratios 0.7 0.8 --seeds 30 --timeouts 25:120 --jobs 1 --out extra_n25.csv --summary-out extra_n25_summary.csv

# Đắt (qua đêm): N=36 quanh vùng chuyển từ khó sang dễ
python benchmark_v2.py --sizes 36 --ratios 0.55 0.65 0.7 --seeds 30 --timeouts 36:300 --jobs 1 --out extra_n36.csv --summary-out extra_n36_summary.csv
```

Vì hạt giống xóa ô được dùng chung cho mọi tỉ lệ, các tỉ lệ mới vẫn thuộc cùng họ đề (ô trống lồng nhau). `analyze.py` đọc lưới (N, ρ) từ dữ liệu nên chạy được trên các tệp này, ví dụ `python analyze.py extra_n25.csv extra_n25_out` (các bảng/hình yêu cầu ô cụ thể của báo cáo sẽ tự bỏ qua nếu thiếu dữ liệu).

## Tái tạo bảng và hình của báo cáo

```bash
python analyze.py results_raw.csv analysis_out
```

Kết quả nằm trong `analysis_out/`:

| Thư mục / file | Nội dung |
|---|---|
| `tables/` | Các bảng 4.2 đến 4.10 dạng CSV (kết quả theo N, chi phí, tỉ trọng bộ giải, phân vùng hiệu năng, Friedman, số timeout chồng lấn, ghép cặp) và các bảng phụ lục A1 (Fisher–Holm), A2 (độ nhạy theo hệ số phạt PAR-k), A3 (regret) |
| `figures/` | Bốn hình của Chương 4 (`fig4_1` đến `fig4_4`) dạng PNG và PDF vector |
| `report.md` | Toàn bộ bảng dạng Markdown |

Ngoài ra script in ra màn hình mục "SO LIEU CHO VAN XUOI" (hệ số tương quan log–log, hệ số mũ, tương quan Spearman, trung vị PAR-2, tỉ số quyết định, p Fisher nhỏ nhất, vùng hiệu năng của từng ô) để đối chiếu với các con số trong báo cáo.

Khoảng tin cậy bootstrap dùng 10 000 lần lấy mẫu với hạt giống cố định 12345 nên chạy lại cho đúng cùng kết quả. Kiểm định Fisher (có hiệu chỉnh Holm) trên số timeout nằm ở cả bảng tổng hợp của `benchmark_v2.py` (cột `p(F,Holm)`) và bảng A1 của `analyze.py`; hai nơi cho cùng giá trị. Thời gian tuyệt đối phụ thuộc phần cứng; số mệnh đề, số biến phụ và đề bài (theo seed) là xác định.

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
