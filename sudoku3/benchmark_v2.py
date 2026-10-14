import argparse
import csv
import math
import multiprocessing
import os
import queue as queue_mod
import random
import statistics
import threading
import time
from concurrent.futures import ThreadPoolExecutor
from typing import Any, Callable, Dict, List, Optional, Tuple

from pysat.solvers import Glucose3


# 1. QUẢN LÝ BIẾN SAT

class VarManager:
    """Cấp phát ID cho biến chính (N^3) và biến phụ."""

    def __init__(self, n: int):
        self.n = n
        self.primary_count = n ** 3
        self.aux_count = 0

    def get_cell_var(self, row: int, col: int, value: int) -> int:
        return self.n * self.n * row + self.n * col + value

    def get_new_vars(self, count: int) -> List[int]:
        start = self.primary_count + self.aux_count + 1
        self.aux_count += count
        return list(range(start, start + count))


# 2. NĂM MÃ HÓA AMO

def binomial_amo(clauses: List[List[int]], variables: List[int], vm: VarManager) -> None:
    k = len(variables)
    for i in range(k):
        for j in range(i + 1, k):
            clauses.append([-variables[i], -variables[j]])


def binary_amo(clauses: List[List[int]], variables: List[int], vm: VarManager) -> None:
    k = len(variables)
    if k <= 1:
        return
    num_bits = math.ceil(math.log2(k))
    aux = vm.get_new_vars(num_bits)
    for idx, var in enumerate(variables):
        bits = format(idx, f"0{num_bits}b")
        for i, bit in enumerate(bits):
            clauses.append([-var, -aux[i]] if bit == "0" else [-var, aux[i]])


def commander_amo(clauses: List[List[int]], variables: List[int], vm: VarManager,
                  group_size: int = 3) -> None:
    k = len(variables)
    if k <= 1:
        return
    if k <= group_size:
        binomial_amo(clauses, variables, vm)
        return
    groups = [variables[i:i + group_size] for i in range(0, k, group_size)]
    commanders = []
    for g in groups:
        if len(g) == 1:
            commanders.append(g[0])
        else:
            cmd = vm.get_new_vars(1)[0]
            commanders.append(cmd)
            for v in g:
                clauses.append([-v, cmd])
            binomial_amo(clauses, g, vm)
    commander_amo(clauses, commanders, vm, group_size)


def product_amo(clauses: List[List[int]], variables: List[int], vm: VarManager) -> None:
    k = len(variables)
    if k <= 1:
        return
    p = math.ceil(math.sqrt(k))
    q = math.ceil(k / p)
    row_vars = vm.get_new_vars(p)
    col_vars = vm.get_new_vars(q)
    for idx, var in enumerate(variables):
        clauses.append([-var, row_vars[idx // q]])
        clauses.append([-var, col_vars[idx % q]])
    binomial_amo(clauses, row_vars, vm)
    binomial_amo(clauses, col_vars, vm)


def sequential_amo(clauses: List[List[int]], variables: List[int], vm: VarManager) -> None:
    k = len(variables)
    if k <= 1:
        return
    aux = vm.get_new_vars(k - 1)
    clauses.append([-variables[0], aux[0]])
    for i in range(1, k - 1):
        x, s_prev, s_curr = variables[i], aux[i - 1], aux[i]
        clauses.append([-x, s_curr])
        clauses.append([-s_prev, s_curr])
        clauses.append([-x, -s_prev])
    clauses.append([-variables[-1], -aux[-1]])


AMO_MAPPINGS: Dict[str, Callable] = {
    "Binomial": binomial_amo,
    "Binary": binary_amo,
    "Commander": commander_amo,
    "Product": product_amo,
    "Sequential": sequential_amo,
}


# 3. MÃ HÓA SUDOKU, GIẢI MÃ, KIỂM CHỨNG

def generate_sudoku_clauses(board: List[List[int]], n: int,
                            amo_func: Callable) -> Tuple[List[List[int]], VarManager]:
    vm = VarManager(n)
    clauses: List[List[int]] = []
    bs = math.isqrt(n)

    for r in range(n):
        for c in range(n):
            if board[r][c] != 0:
                clauses.append([vm.get_cell_var(r, c, board[r][c])])

    def exactly_one(variables: List[int]) -> None:
        clauses.append(variables)
        amo_func(clauses, variables, vm)

    for r in range(n):
        for c in range(n):
            exactly_one([vm.get_cell_var(r, c, v) for v in range(1, n + 1)])
    for r in range(n):
        for v in range(1, n + 1):
            exactly_one([vm.get_cell_var(r, c, v) for c in range(n)])
    for c in range(n):
        for v in range(1, n + 1):
            exactly_one([vm.get_cell_var(r, c, v) for r in range(n)])
    for br in range(0, n, bs):
        for bc in range(0, n, bs):
            for v in range(1, n + 1):
                exactly_one([vm.get_cell_var(r, c, v)
                             for r in range(br, br + bs) for c in range(bc, bc + bs)])
    return clauses, vm


def decode_sat_solution(model: List[int], n: int, vm: VarManager) -> List[List[int]]:
    grid = [[0] * n for _ in range(n)]
    pos = {v for v in model if v > 0}
    for r in range(n):
        for c in range(n):
            for v in range(1, n + 1):
                if vm.get_cell_var(r, c, v) in pos:
                    grid[r][c] = v
                    break
    return grid


def verify_sudoku_solution(grid: List[List[int]], puzzle: List[List[int]], n: int) -> bool:
    """Kiểm tra hàng, cột, khối VÀ các ô gợi ý ban đầu được giữ nguyên."""
    bs = math.isqrt(n)
    expected = set(range(1, n + 1))
    for i in range(n):
        if set(grid[i]) != expected:
            return False
        if {grid[r][i] for r in range(n)} != expected:
            return False
    for br in range(0, n, bs):
        for bc in range(0, n, bs):
            if {grid[r][c] for r in range(br, br + bs) for c in range(bc, bc + bs)} != expected:
                return False
    for r in range(n):
        for c in range(n):
            if puzzle[r][c] != 0 and grid[r][c] != puzzle[r][c]:
                return False
    return True


# 4. SINH ĐỀ BÀI (seed bảng đầy đủ và seed chọn ô xóa độc lập)

def generate_complete_sudoku(n: int, seed: int) -> List[List[int]]:
    bs = math.isqrt(n)
    if bs * bs != n:
        raise ValueError("n phải là số chính phương")
    rng = random.Random(seed)
    base = [[(bs * (r % bs) + r // bs + c) % n for c in range(n)] for r in range(n)]
    rows = [band * bs + row for band in rng.sample(range(bs), bs) for row in rng.sample(range(bs), bs)]
    cols = [stack * bs + col for stack in rng.sample(range(bs), bs) for col in rng.sample(range(bs), bs)]
    numbers = rng.sample(range(1, n + 1), n)
    return [[numbers[base[rows[r]][cols[c]]] for c in range(n)] for r in range(n)]


def generate_sudoku(n: int, empty_cells: int, seed: int) -> List[List[int]]:
    board = generate_complete_sudoku(n, seed)
    rng = random.Random(seed * 1_000_003 + 7919)  # luồng ngẫu nhiên riêng cho việc xóa ô
    positions = [(r, c) for r in range(n) for c in range(n)]
    rng.shuffle(positions)
    puzzle = [row[:] for row in board]
    for r, c in positions[:empty_cells]:
        puzzle[r][c] = 0
    return puzzle


# 5. TIẾN TRÌNH CON: ENCODE -> LOAD -> SOLVE -> VERIFY

def benchmark_worker(enc_name: str, puzzle: List[List[int]], n: int, result_queue) -> None:
    try:
        amo_func = AMO_MAPPINGS[enc_name]

        t0 = time.perf_counter()
        clauses, vm = generate_sudoku_clauses(puzzle, n, amo_func)
        enc_time = time.perf_counter() - t0

        solver = Glucose3()
        t1 = time.perf_counter()
        solver.append_formula(clauses)
        load_time = time.perf_counter() - t1

        t2 = time.perf_counter()
        solved = solver.solve()
        sol_time = time.perf_counter() - t2

        valid = False
        if solved:
            grid = decode_sat_solution(solver.get_model(), n, vm)
            valid = verify_sudoku_solution(grid, puzzle, n)

        stats = solver.accum_stats()
        solver.delete()

        result_queue.put({
            "status": "OK",
            "primary": vm.primary_count,
            "aux": vm.aux_count,
            "clauses": len(clauses),
            "enc_time": enc_time,
            "load_time": load_time,
            "sol_time": sol_time,
            "total_time": enc_time + load_time + sol_time,
            "conflicts": stats.get("conflicts", 0),
            "decisions": stats.get("decisions", 0),
            "propagations": stats.get("propagations", 0),
            "restarts": stats.get("restarts", 0),
            "verified": int(bool(solved and valid)),
        })
    except Exception as e:  # noqa: BLE001
        result_queue.put({"status": "ERROR", "error": f"{type(e).__name__}: {e}"})


STARTUP_GRACE = 15.0  # giây chờ thêm cho khởi động tiến trình + giải mã/kiểm chứng


def run_single_test(enc_name: str, puzzle: List[List[int]], n: int, timeout: float) -> Dict[str, Any]:
    """Timeout áp dụng lên (enc + load + solve). Tiến trình bị kill sau timeout + grace;
    nếu hoàn tất nhưng tổng enc+load+solve > timeout thì vẫn tính là TIMEOUT."""
    ctx = multiprocessing.get_context("spawn")
    q = ctx.Queue()
    proc = ctx.Process(target=benchmark_worker, args=(enc_name, puzzle, n, q))
    proc.start()
    proc.join(timeout + STARTUP_GRACE)

    if proc.is_alive():
        proc.terminate()
        proc.join()
        res: Dict[str, Any] = {"status": "TIMEOUT"}
    else:
        try:
            res = q.get(timeout=3)
        except queue_mod.Empty:
            res = {"status": "ERROR", "error": f"process exit code {proc.exitcode}, no result"}
        if res.get("status") == "OK" and res["total_time"] > timeout:
            res["status"] = "TIMEOUT"

    try:
        proc.close()
        q.close()
    except Exception:  # noqa: BLE001
        pass
    return res


# 6. GHI/ĐỌC CSV, CHẠY THEO LÔ, RESUME

CSV_FIELDS = [
    "n", "empty_ratio", "empty_cells", "encoding", "seed", "timeout", "status",
    "primary", "aux", "clauses", "enc_time", "load_time", "sol_time", "total_time",
    "par2", "conflicts", "decisions", "propagations", "restarts", "verified", "error",
]


def load_done_keys(path: str) -> set:
    done = set()
    if os.path.exists(path):
        with open(path, newline="", encoding="utf-8") as f:
            for row in csv.DictReader(f):
                done.add((int(row["n"]), float(row["empty_ratio"]), row["encoding"], int(row["seed"])))
    return done


def run_experiments(args) -> None:
    timeouts = parse_timeouts(args.timeouts)
    done = load_done_keys(args.out)
    new_file = not os.path.exists(args.out) or os.path.getsize(args.out) == 0

    tasks = []
    for n in args.sizes:
        for ratio in args.ratios:
            for seed in range(args.seeds):
                for enc in args.encodings:  # xen kẽ các mã hóa theo seed -> nếu dừng giữa chừng vẫn cân bằng
                    if (n, ratio, enc, seed) not in done:
                        tasks.append((n, ratio, enc, seed))

    total_planned = len(args.sizes) * len(args.ratios) * args.seeds * len(args.encodings)
    print(f"Tổng số lượt: {total_planned} | đã có: {total_planned - len(tasks)} | cần chạy: {len(tasks)}")
    print(f"Timeout theo kích thước: {timeouts} | jobs song song: {args.jobs}")
    if not tasks:
        return

    lock = threading.Lock()
    counter = {"done": 0}
    fout = open(args.out, "a", newline="", encoding="utf-8")
    writer = csv.DictWriter(fout, fieldnames=CSV_FIELDS)
    if new_file:
        writer.writeheader()
        fout.flush()
    t_begin = time.time()

    def do_task(task):
        n, ratio, enc, seed = task
        timeout = timeouts[n]
        empty = round(n * n * ratio)
        puzzle = generate_sudoku(n, empty, seed)
        res = run_single_test(enc, puzzle, n, timeout)

        row = {"n": n, "empty_ratio": ratio, "empty_cells": empty, "encoding": enc,
               "seed": seed, "timeout": timeout, "status": res["status"]}
        if res["status"] == "OK":
            row.update({k: res[k] for k in (
                "primary", "aux", "clauses", "enc_time", "load_time", "sol_time", "total_time",
                "conflicts", "decisions", "propagations", "restarts", "verified")})
            row["par2"] = res["total_time"]
        elif res["status"] == "TIMEOUT":
            row["par2"] = 2 * timeout
            # Nếu có số liệu kích thước từ lượt hoàn tất-nhưng-quá-giờ thì giữ lại
            for k in ("primary", "aux", "clauses", "enc_time", "load_time", "sol_time",
                      "total_time", "conflicts", "decisions", "propagations", "restarts"):
                if k in res:
                    row[k] = res[k]
        else:
            row["error"] = res.get("error", "")

        with lock:
            writer.writerow(row)
            fout.flush()
            counter["done"] += 1
            elapsed = time.time() - t_begin
            print(f"[{counter['done']}/{len(tasks)}] N={n} empty={ratio:.0%} {enc:<10} seed={seed:<3} "
                  f"-> {row['status']:<7} "
                  + (f"total={row.get('total_time', 0):.2f}s " if res['status'] == 'OK' else "")
                  + f"(elapsed {elapsed/60:.1f} min)", flush=True)

    try:
        if args.jobs <= 1:
            for t in tasks:
                do_task(t)
        else:
            with ThreadPoolExecutor(max_workers=args.jobs) as ex:
                list(ex.map(do_task, tasks))
    finally:
        fout.close()


# 7. THỐNG KÊ VÀ BÁO CÁO TỔNG HỢP

def fisher_exact_two_sided(a: int, b: int, c: int, d: int) -> float:
    """Kiểm định chính xác Fisher hai phía cho bảng [[a,b],[c,d]]."""
    r1, r2, c1 = a + b, c + d, a + c
    total = r1 + r2

    def prob(x: int) -> float:
        return math.comb(r1, x) * math.comb(r2, c1 - x) / math.comb(total, c1)

    p_obs = prob(a)
    lo, hi = max(0, c1 - r2), min(r1, c1)
    return min(1.0, sum(prob(x) for x in range(lo, hi + 1) if prob(x) <= p_obs * (1 + 1e-9)))


def bootstrap_ci_mean(values: List[float], iters: int = 2000, seed: int = 0) -> Tuple[float, float]:
    if len(values) < 2:
        return (values[0], values[0]) if values else (0.0, 0.0)
    rng = random.Random(seed)
    k = len(values)
    means = sorted(sum(values[rng.randrange(k)] for _ in range(k)) / k for _ in range(iters))
    return means[int(0.025 * iters)], means[int(0.975 * iters)]


def _f(x: str) -> Optional[float]:
    return float(x) if x not in ("", None) else None


def summarize(path: str, baseline: str = "Binomial", out_summary: Optional[str] = None) -> None:
    if not os.path.exists(path):
        print(f"Không tìm thấy {path}")
        return
    with open(path, newline="", encoding="utf-8") as f:
        rows = list(csv.DictReader(f))

    groups: Dict[Tuple[int, float], Dict[str, List[dict]]] = {}
    for r in rows:
        groups.setdefault((int(r["n"]), float(r["empty_ratio"])), {}).setdefault(r["encoding"], []).append(r)

    summary_rows = []
    width = 190
    print("\n" + "=" * width)
    print("TỔNG HỢP KẾT QUẢ (thời gian: giây; enc/load/sol/conflicts/decisions: trung bình trên các lượt HOÀN TẤT)")
    print("=" * width)

    for (n, ratio) in sorted(groups):
        enc_groups = groups[(n, ratio)]
        any_row = next(iter(next(iter(enc_groups.values()))))
        print(f"\n[ N = {n}x{n} | ô trống {ratio:.0%} ({any_row['empty_cells']} ô) | timeout {any_row['timeout']}s ]")
        header = (f"{'Encoding':<11}|{'Aux':>8}|{'Clauses':>9}|{'Enc':>7}|{'Load':>7}|{'Sol(mean)':>10}|"
                  f"{'Sol(med)':>9}|{'PAR-2 mean [95% CI]':>27}|{'PAR-2 med':>10}|{'Conflicts':>10}|"
                  f"{'Decisions':>10}|{'Verified':>9}|{'Timeouts':>9}|{'Err':>4}|{'p(Fisher)':>10}")
        print("-" * len(header))
        print(header)
        print("-" * len(header))

        base_rows = enc_groups.get(baseline, [])
        base_to = sum(r["status"] == "TIMEOUT" for r in base_rows)
        base_ok_cnt = sum(r["status"] in ("OK", "TIMEOUT") for r in base_rows)

        for enc in AMO_MAPPINGS:
            rs = enc_groups.get(enc)
            if not rs:
                continue
            valid_runs = [r for r in rs if r["status"] in ("OK", "TIMEOUT")]
            errs = sum(r["status"] == "ERROR" for r in rs)
            ok = [r for r in rs if r["status"] == "OK"]
            to = sum(r["status"] == "TIMEOUT" for r in rs)
            par2 = [float(r["par2"]) for r in valid_runs]

            def mean_of(key):
                vals = [float(r[key]) for r in ok if r.get(key) not in ("", None)]
                return statistics.mean(vals) if vals else None

            def med_of(key):
                vals = [float(r[key]) for r in ok if r.get(key) not in ("", None)]
                return statistics.median(vals) if vals else None

            size_src = next((r for r in rs if r.get("clauses") not in ("", None)), None)
            aux = size_src["aux"] if size_src else "-"
            cls = size_src["clauses"] if size_src else "-"

            def fmt(v, spec):
                return format(v, spec) if v is not None else "-"

            if par2:
                m = statistics.mean(par2)
                lo, hi = bootstrap_ci_mean(par2)
                par2_str = f"{m:.3f} [{lo:.3f},{hi:.3f}]"
                par2_med = statistics.median(par2)
            else:
                m = par2_med = None
                par2_str = "-"

            verified = "-" if not ok else ("PASSED" if all(r["verified"] == "1" for r in ok) else "FAILED")

            if enc != baseline and base_ok_cnt and valid_runs:
                p = fisher_exact_two_sided(to, len(valid_runs) - to, base_to, base_ok_cnt - base_to)
                p_str = f"{p:.3f}"
            else:
                p_str = "-"

            conf = mean_of("conflicts")
            dec = mean_of("decisions")
            print(f"{enc:<11}|{aux:>8}|{cls:>9}|{fmt(mean_of('enc_time'), '.3f'):>7}|"
                  f"{fmt(mean_of('load_time'), '.3f'):>7}|{fmt(mean_of('sol_time'), '.3f'):>10}|"
                  f"{fmt(med_of('sol_time'), '.3f'):>9}|{par2_str:>27}|{fmt(par2_med, '.3f'):>10}|"
                  f"{fmt(conf, '.0f'):>10}|{fmt(dec, '.0f'):>10}|{verified:>9}|"
                  f"{f'{to}/{len(valid_runs)}':>9}|{errs:>4}|{p_str:>10}")

            summary_rows.append({
                "n": n, "empty_ratio": ratio, "encoding": enc, "aux": aux, "clauses": cls,
                "enc_time": mean_of("enc_time"), "load_time": mean_of("load_time"),
                "sol_time_mean": mean_of("sol_time"), "sol_time_median": med_of("sol_time"),
                "par2_mean": m, "par2_median": par2_med, "conflicts": conf, "decisions": dec,
                "timeouts": to, "runs": len(valid_runs), "errors": errs, "verified": verified,
            })

    if out_summary and summary_rows:
        with open(out_summary, "w", newline="", encoding="utf-8") as f:
            w = csv.DictWriter(f, fieldnames=list(summary_rows[0].keys()))
            w.writeheader()
            w.writerows(summary_rows)
        print(f"\nĐã ghi bảng tổng hợp: {out_summary}")
    print("\nGhi chú: p(Fisher) so sánh tỉ lệ timeout với", baseline,
          "(hai phía, chưa hiệu chỉnh đa so sánh). Dữ liệu thô từng seed nằm trong", path)


# 8. CLI

def parse_timeouts(spec: str) -> Dict[int, float]:
    out = {}
    for part in spec.split(","):
        k, v = part.split(":")
        out[int(k)] = float(v)
    return out


PRESETS = {
    # vài phút: kiểm tra nhanh pipeline
    "quick": dict(sizes=[9, 16, 25], seeds=5, ratios=[0.5], timeouts="9:30,16:30,25:60,36:60"),
    # N<=25 đầy đủ: nhiều seed, quét tỉ lệ ô trống
    "medium": dict(sizes=[9, 16, 25], seeds=30, ratios=[0.3, 0.4, 0.5, 0.6],
                   timeouts="9:30,16:30,25:120,36:300"),
    # Cấu hình đầy đủ theo đề xuất; N=36 có thể mất RẤT nhiều giờ
    "full": dict(sizes=[9, 16, 25, 36], seeds=30, ratios=[0.3, 0.4, 0.5, 0.6],
                 timeouts="9:30,16:30,25:120,36:300"),
}


def build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(description="Benchmark các mã hóa AMO cho Sudoku (Glucose3)")
    p.add_argument("--preset", choices=list(PRESETS), help="cấu hình dựng sẵn (bị ghi đè bởi tham số cụ thể)")
    p.add_argument("--sizes", type=int, nargs="+", help="các kích thước N (số chính phương)")
    p.add_argument("--seeds", type=int, help="số seed mỗi cấu hình (seed 0..S-1)")
    p.add_argument("--ratios", type=float, nargs="+", help="các tỉ lệ ô trống, ví dụ 0.3 0.5 0.6")
    p.add_argument("--timeouts", type=str, help="timeout theo N, ví dụ 9:30,16:30,25:120,36:300")
    p.add_argument("--encodings", nargs="+", default=list(AMO_MAPPINGS), choices=list(AMO_MAPPINGS))
    p.add_argument("--jobs", type=int, default=1,
                   help="số lượt chạy song song (mặc định 1 để đo thời gian sạch; >1 làm nhiễu thời gian)")
    p.add_argument("--out", default="results_raw.csv", help="CSV thô, từng lượt chạy")
    p.add_argument("--summary-out", default="results_summary.csv")
    p.add_argument("--baseline", default="Binomial", help="mã hóa làm mốc cho kiểm định Fisher")
    p.add_argument("--summary-only", action="store_true", help="chỉ đọc CSV và in bảng tổng hợp")
    return p


def main() -> None:
    args = build_parser().parse_args()
    if not args.summary_only:
        preset = PRESETS[args.preset or "quick"]
        for key, val in preset.items():
            if getattr(args, key) is None:
                setattr(args, key, val)
        run_experiments(args)
    summarize(args.out, args.baseline, args.summary_out)


if __name__ == "__main__":
    multiprocessing.freeze_support()
    main()