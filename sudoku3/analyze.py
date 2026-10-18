import itertools
import math
import os
import sys

import numpy as np
import pandas as pd
from scipy import stats
import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt

ORDER = ["Binomial", "Binary", "Commander", "Product", "Sequential"]
COLORS = {"Binomial": "#1f77b4", "Binary": "#ff7f0e", "Commander": "#2ca02c",
          "Product": "#d62728", "Sequential": "#9467bd"}

# Được gán lại từ dữ liệu trong configure(); giá trị mặc định là lưới của báo cáo.
NS = [9, 16, 25, 36]
RS = [0.3, 0.4, 0.5, 0.6]
PCT = {r: int(round(r * 100)) for r in RS}

# Ngưỡng tỉ trọng bộ giải (Sol/Total, %) để phân vùng hiệu năng (Mục 4.5)
SHARE_I, SHARE_III = 11.0, 80.0


def configure(D):
    """Lấy lưới (N, rho) từ dữ liệu thay vì viết cứng, để chạy được trên tệp preset nhỏ."""
    global NS, RS, PCT
    NS = sorted(int(x) for x in D.df.n.unique())
    RS = sorted(float(x) for x in D.df.empty_ratio.unique())
    PCT = {r: int(round(r * 100)) for r in RS}


# ------------------------------------------------------------------ thống kê
def boot_ci(x, iters=10000, seed=12345):
    x = np.asarray(x, float)
    rng = np.random.default_rng(seed)
    idx = rng.integers(0, len(x), size=(iters, len(x)))
    m = x[idx].mean(axis=1)
    return float(np.percentile(m, 2.5)), float(np.percentile(m, 97.5))


def holm(ps):
    ps = np.asarray(ps, float)
    m = len(ps)
    order = np.argsort(ps)
    adj = np.empty(m)
    run = 0.0
    for rank, i in enumerate(order):
        run = max(run, (m - rank) * ps[i])
        adj[i] = min(1.0, run)
    return adj


def wilcoxon_p(a, b):
    d = np.asarray(a, float) - np.asarray(b, float)
    if len(d) == 0 or np.all(d == 0):
        return 1.0
    return float(stats.wilcoxon(a, b, zero_method="wilcox").pvalue)


def fmt_p(p):
    if p >= 0.001:
        return f"{p:.3f}"
    return f"{p:.1e}"


def paired_diff_ci(a, b, iters=10000, seed=12345):
    """Trung bình hiệu a-b (ghép cặp theo seed) và khoảng tin cậy bootstrap phân vị 95%."""
    d = np.asarray(a, float) - np.asarray(b, float)
    idx = np.random.default_rng(seed).integers(0, len(d), size=(iters, len(d)))
    m = d[idx].mean(axis=1)
    return float(d.mean()), float(np.percentile(m, 2.5)), float(np.percentile(m, 97.5))


# ------------------------------------------------------------------ dữ liệu
class Data:
    def __init__(self, path):
        df = pd.read_csv(path)
        df["to"] = (df.status == "TIMEOUT").astype(int)
        self.df = df
        self.ok = df[df.status == "OK"].copy()
        self.T = df.groupby("n").timeout.first().to_dict()
        self.cells = {}
        for (n, r, e), g in df.groupby(["n", "empty_ratio", "encoding"]):
            ok = g[g.status == "OK"]
            par2 = g.sort_values("seed").par2.values
            lo, hi = boot_ci(par2)
            sized = g[g.clauses.notna()]
            src = sized.iloc[0] if len(sized) else None
            self.cells[(n, r, e)] = dict(
                nto=int(g.to.sum()), N=len(g), nok=len(ok),
                par2=par2.mean(), lo=lo, hi=hi, par2med=float(np.median(par2)),
                enc=ok.enc_time.mean(), load=ok.load_time.mean(), sol=ok.sol_time.mean(),
                total=ok.total_time.mean(), conf=ok.conflicts.mean(), dec=ok.decisions.mean(),
                aux=int(src.aux) if src is not None else np.nan,
                cls=int(src.clauses) if src is not None else np.nan,
                E=int(g.empty_cells.iloc[0]),
                share=100 * ok.sol_time.sum() / ok.total_time.sum() if len(ok) else np.nan,
            )

    def has(self, n, r):
        return all((n, r, e) in self.cells for e in ORDER)

    def wide(self, n, r, col="par2"):
        s = self.df[(self.df.n == n) & (self.df.empty_ratio == r)].pivot(
            index="seed", columns="encoding", values=col)
        return s[ORDER]

    def friedman(self, n, r):
        W = self.wide(n, r)
        fr = stats.friedmanchisquare(*[W[e] for e in ORDER])
        ranks = W.rank(axis=1).mean()
        pairs = list(itertools.combinations(ORDER, 2))
        adj = holm([wilcoxon_p(W[a], W[b]) for a, b in pairs])
        return dict(chi=float(fr.statistic), p=float(fr.pvalue), ranks=ranks,
                    padj=dict(zip(pairs, adj)))

    def common_seeds(self, n, r):
        St = self.wide(n, r, "status")
        return list(St.index[(St == "OK").all(axis=1)])

    def paired(self, n, r):
        seeds = self.common_seeds(n, r)
        W = {c: self.wide(n, r, c).loc[seeds] for c in
             ["sol_time", "conflicts", "decisions", "propagations"]}
        res = {}
        for c in ["sol_time", "conflicts", "decisions"]:
            ps = [wilcoxon_p(W[c]["Binomial"], W[c][e]) for e in ORDER[1:]]
            for e, a in zip(ORDER[1:], holm(ps)):
                res[(c, e)] = (float((W[c][e] / W[c]["Binomial"]).median()), float(a))
        enc = {}
        for e in ORDER:
            enc[e] = dict(
                sol=float(W["sol_time"][e].median()), conf=float(W["conflicts"][e].median()),
                dec=float(W["decisions"][e].median()),
                kcps=float((W["conflicts"][e] / W["sol_time"][e]).median() / 1e3),
                ppc=float((W["propagations"][e] / W["conflicts"][e]).median()))
        return len(seeds), enc, res


# ------------------------------------------------------------------ các bảng
def table_results(D, n):
    rows = []
    for r in RS:
        if not D.has(n, r):
            continue
        for e in ORDER:
            c = D.cells[(n, r, e)]
            rows.append({
                "rho": f"{PCT[r]}%", "E": c["E"], "G": n * n - c["E"], "Encoding": e,
                "Aux": c["aux"], "Clauses": c["cls"],
                "Enc": c["enc"], "Load": c["load"], "Sol": c["sol"],
                "PAR2": c["par2"], "PAR2_med": c["par2med"], "CI_lo": c["lo"], "CI_hi": c["hi"],
                "Conflicts": c["conf"], "Decisions": c["dec"],
                "Timeouts": f"{c['nto']}/{c['N']}"})
    return pd.DataFrame(rows)


def table_cost(D, n=36, r=0.3):
    if not D.has(n, r):
        return pd.DataFrame()
    o = D.ok.assign(enc_us=D.ok.enc_time / D.ok.clauses * 1e6,
                    load_us=D.ok.load_time / D.ok.clauses * 1e6)
    g = o[o.n == n].groupby("encoding")[["enc_us", "load_us"]].mean()
    rows = []
    for e in ORDER:
        c = D.cells[(n, r, e)]
        rows.append({"Encoding": e, "Clauses": c["cls"], "Enc": c["enc"], "Load": c["load"],
                     "Enc+Load": c["enc"] + c["load"], "Sol": c["sol"], "PAR2": c["par2"],
                     "Enc_us_per_clause": g.enc_us[e], "Load_us_per_clause": g.load_us[e]})
    return pd.DataFrame(rows)


def table_share(D):
    rows = []
    for n in NS:
        for r in RS:
            if not D.has(n, r):
                continue
            d = {"N": n, "rho": f"{PCT[r]}%"}
            d.update({e: D.cells[(n, r, e)]["share"] for e in ORDER})
            rows.append(d)
    return pd.DataFrame(rows)


def zone_of(shares):
    """Vùng hiệu năng theo tỉ trọng bộ giải: I < 11% tối đa; III khi mọi mã hóa >= 80%; còn lại II."""
    sh = [s for s in shares if not np.isnan(s)]
    if not sh:
        return "-"
    if max(sh) < SHARE_I:
        return "I (công thức)"
    if min(sh) >= SHARE_III:
        return "III (tìm kiếm)"
    return "II (chuyển tiếp)"


def table_zones(D):
    rows = []
    for n in NS:
        for r in RS:
            if not D.has(n, r):
                continue
            sh = [D.cells[(n, r, e)]["share"] for e in ORDER]
            rows.append({"N": n, "rho": f"{PCT[r]}%", "share_min": min(sh), "share_max": max(sh),
                         "Zone": zone_of(sh)})
    return pd.DataFrame(rows)


def table_friedman(D):
    rows, FR = [], {}
    for n in NS:
        for r in RS:
            if not D.has(n, r):
                continue
            f = D.friedman(n, r)
            FR[(n, r)] = f
            d = {"N": n, "rho": f"{PCT[r]}%", "chi2": f["chi"], "p": f["p"]}
            d.update({e: f["ranks"][e] for e in ORDER})
            d["sig_pairs"] = f"{sum(v < 0.05 for v in f['padj'].values())}/10"
            rows.append(d)
    return pd.DataFrame(rows), FR


def table_overlap(D):
    out = {}
    for r in (0.5, 0.6):
        if not D.has(36, r):
            continue
        St = D.wide(36, r, "status")
        out[f"rho={PCT[r]}%"] = (St == "TIMEOUT").sum(axis=1).value_counts().to_dict()
    if not out:
        return pd.DataFrame()
    return pd.DataFrame({k: [v.get(i, 0) for i in range(6)] for k, v in out.items()},
                        index=pd.Index(range(6), name="k_encodings_timeout")).reset_index()


def table_paired(D, cells=((25, 0.5), (25, 0.6), (36, 0.6))):
    rows = []
    for n, r in cells:
        if not D.has(n, r):
            continue
        ns, enc, res = D.paired(n, r)
        for e in ORDER:
            m = enc[e]
            d = {"N": n, "rho": f"{PCT[r]}%", "common_seeds": ns, "Encoding": e,
                 "Sol_median": m["sol"]}
            if e == "Binomial":
                d.update({"Sol_x": np.nan, "Sol_p": np.nan, "Conf_x": np.nan, "Conf_p": np.nan,
                          "Dec_x": np.nan, "Dec_p": np.nan})
            else:
                d.update({"Sol_x": res[("sol_time", e)][0], "Sol_p": res[("sol_time", e)][1],
                          "Conf_x": res[("conflicts", e)][0], "Conf_p": res[("conflicts", e)][1],
                          "Dec_x": res[("decisions", e)][0], "Dec_p": res[("decisions", e)][1]})
            d.update({"Conflicts_median": m["conf"], "Decisions_median": m["dec"],
                      "kconf_per_s": m["kcps"], "Prop_per_conf": m["ppc"]})
            rows.append(d)
    return pd.DataFrame(rows)


def table_fisher(D, baseline="Binomial"):
    """Fisher hai phía trên số timeout so với mốc, hiệu chỉnh Holm trong từng ô (4 so sánh)."""
    rows = []
    encs = [e for e in ORDER if e != baseline]
    for n in NS:
        for r in RS:
            if not D.has(n, r):
                continue
            b = D.cells[(n, r, baseline)]
            raw = []
            for e in encs:
                c = D.cells[(n, r, e)]
                raw.append(stats.fisher_exact(
                    [[c["nto"], c["N"] - c["nto"]], [b["nto"], b["N"] - b["nto"]]])[1])
            for e, p in zip(encs, holm(raw)):
                rows.append({"N": n, "rho": f"{PCT[r]}%", "Encoding": e,
                             "Timeouts": f"{D.cells[(n, r, e)]['nto']}/{D.cells[(n, r, e)]['N']}",
                             "p_Fisher_Holm": p})
    return pd.DataFrame(rows)


def table_par_k(D, n=36, r=0.6, ks=(1, 2, 10)):
    """Độ nhạy theo hệ số phạt PAR-k và hiệu ghép cặp (mã hóa - Binomial) kèm CI bootstrap."""
    if not D.has(n, r):
        return pd.DataFrame()
    d = D.df[(D.df.n == n) & (D.df.empty_ratio == r)].copy()
    out = {}
    for k in ks:
        d["pk"] = np.where(d.status == "OK", d.total_time, k * D.T[n])
        out[k] = d.pivot(index="seed", columns="encoding", values="pk")[ORDER]
    rows = []
    for e in ORDER:
        row = {"N": n, "rho": f"{PCT[r]}%", "Encoding": e}
        for k in ks:
            row[f"PAR-{k}"] = out[k][e].mean()
        if e != "Binomial":
            for k in ks:
                m, lo, hi = paired_diff_ci(out[k][e], out[k]["Binomial"])
                row[f"diff_PAR-{k}"] = m
                row[f"diff_PAR-{k}_lo"] = lo
                row[f"diff_PAR-{k}_hi"] = hi
        rows.append(row)
    return pd.DataFrame(rows)


def table_regret(D):
    """Regret = PAR-2 của mã hóa / PAR-2 tốt nhất trong cùng ô (N, rho); thống kê trên mọi ô."""
    rows = []
    for n in NS:
        for r in RS:
            if not D.has(n, r):
                continue
            p = {e: D.cells[(n, r, e)]["par2"] for e in ORDER}
            best = min(p.values())
            rows.append({e: p[e] / best for e in ORDER})
    df = pd.DataFrame(rows)
    return pd.DataFrame({"Encoding": ORDER, "max_regret": [df[e].max() for e in ORDER],
                         "mean_regret": [df[e].mean() for e in ORDER],
                         "cells_best": [int((df[e] == 1.0).sum()) for e in ORDER]})


def table_formula_check(D):
    """Số cấu hình có số mệnh đề thay đổi giữa các seed (phải bằng 0)."""
    g = D.df.dropna(subset=["clauses"]).groupby(["n", "empty_ratio", "encoding"])
    bad = g.clauses.nunique()
    return int((bad > 1).sum())


def prose_numbers(D):
    """In các con số đang được trích trong văn xuôi của báo cáo để đối chiếu."""
    print("\n=== SO LIEU CHO VAN XUOI ===")
    o = D.ok
    for col, name in [("enc_time", "sinh"), ("load_time", "nap")]:
        x, y = np.log(o.clauses), np.log(o[col])
        print(f"Thoi gian {name} theo so menh de (log-log): r = {stats.pearsonr(x, y)[0]:.3f}, "
              f"he so mu = {stats.linregress(x, y).slope:.2f}")
    for n, r in [(36, .6), (25, .6)]:
        if not D.has(n, r):
            continue
        St, S = D.wide(n, r, "status"), D.wide(n, r, "sol_time")
        rho = []
        for a, b in itertools.combinations(ORDER, 2):
            m = (St[a] == "OK") & (St[b] == "OK")
            rho.append(stats.spearmanr(S.loc[m, a], S.loc[m, b])[0])
        print(f"Spearman thoi gian giai N={n}, rho={PCT[r]}%: {min(rho):.2f} .. {max(rho):.2f}")
    if D.has(36, .6):
        c = D.cells[(36, .6, "Binomial")]
        print(f"Binomial N=36 rho=60%: PAR-2 trung binh {c['par2']:.1f}, trung vi {c['par2med']:.1f}")
        _, enc, res = D.paired(36, .6)
        print("N=36 rho=60% ti so quyet dinh so voi Binomial:",
              {e: round(res[("decisions", e)][0], 2) for e in ORDER[1:]})
        print("N=36 rho=60% ti so thoi gian giai:",
              {e: round(res[("sol_time", e)][0], 2) for e in ORDER[1:]})
        print("N=36 rho=60% Prop/conf:", {e: round(enc[e]["ppc"]) for e in ORDER})
    # phan vung hieu nang
    print("Vung hieu nang:", {(n, PCT[r]): zone_of([D.cells[(n, r, e)]["share"] for e in ORDER])
                              for n in NS for r in RS if D.has(n, r)})
    # Fisher nho nhat o N=36, rho=60%
    tf = table_fisher(D)
    sub = tf[(tf.N == 36) & (tf.rho == "60%")]
    if len(sub):
        print(f"Fisher-Holm N=36 rho=60%: p nho nhat = {sub.p_Fisher_Holm.min():.3f}")


# ------------------------------------------------------------------ ghi file
def md_table(df):
    def f(v):
        if isinstance(v, (float, np.floating)):
            if np.isnan(v):
                return "-"
            return f"{v:.4g}" if abs(v) < 1000 else f"{v:,.0f}"
        return str(v)
    head = "| " + " | ".join(map(str, df.columns)) + " |"
    sep = "|" + "|".join("---" for _ in df.columns) + "|"
    body = ["| " + " | ".join(f(v) for v in row) + " |" for row in df.itertuples(index=False)]
    return "\n".join([head, sep] + body)


def save_fig(fig, path):
    fig.tight_layout()
    fig.savefig(path, dpi=200)
    fig.savefig(os.path.splitext(path)[0] + ".pdf")  # bản vector để in
    plt.close(fig)


# ------------------------------------------------------------------ hình
def fig_bar(D, key, encs, ylabel, title, path, r=0.5):
    fig, ax = plt.subplots(figsize=(8, 4.5))
    w = 0.8 / len(encs)
    for i, e in enumerate(encs):
        vals = [D.cells[(n, r, e)][key] for n in NS]
        ax.bar(np.arange(len(NS)) + i * w, vals, w, color=COLORS[e], label=e)
    ax.set_xticks(np.arange(len(NS)) + w * (len(encs) - 1) / 2)
    ax.set_xticklabels([f"{n}x{n}" for n in NS])
    ax.set_yscale("log"); ax.set_ylabel(ylabel); ax.set_xlabel("Kích thước Sudoku")
    ax.set_title(title); ax.grid(axis="y", alpha=.3); ax.legend()
    save_fig(fig, path)


def fig_par2(D, path):
    nrows = (len(NS) + 1) // 2
    fig, axs = plt.subplots(nrows, 2, figsize=(10, 3.5 * nrows), squeeze=False)
    axl = axs.ravel()
    for ax, n in zip(axl, NS):
        rs = [r for r in RS if D.has(n, r)]
        for e in ORDER:
            ax.plot([PCT[r] for r in rs], [D.cells[(n, r, e)]["par2"] for r in rs],
                    marker="o", ms=4, color=COLORS[e], label=e)
        ax.axhline(2 * D.T[n], ls="--", c="k", lw=1)
        ax.set_yscale("log"); ax.set_xticks([PCT[r] for r in rs]); ax.grid(alpha=.3)
        ax.set_title(f"N = {n}"); ax.set_xlabel("Tỉ lệ ô trống ρ (%)"); ax.set_ylabel("PAR-2 (s)")
    for ax in axl[len(NS):]:
        ax.set_visible(False)
    axl[0].legend(fontsize=8)
    fig.suptitle("PAR-2 theo tỉ lệ ô trống (nét đứt: mức phạt 2T)")
    save_fig(fig, path)


def fig_cactus(D, path):
    panels = [(n, r) for n, r in [(25, .6), (36, .4), (36, .5), (36, .6)] if D.has(n, r)]
    if not panels:
        return
    nrows = (len(panels) + 1) // 2
    fig, axs = plt.subplots(nrows, 2, figsize=(10, 3.5 * nrows), squeeze=False)
    axl = axs.ravel()
    nseed = int(D.df.seed.max()) + 1
    for ax, (n, r) in zip(axl, panels):
        sub = D.ok[(D.ok.n == n) & (D.ok.empty_ratio == r)]
        for e in ORDER:
            t = np.sort(sub[sub.encoding == e].total_time.values)
            if len(t):
                ax.plot(np.arange(1, len(t) + 1), t, marker="o", ms=3, color=COLORS[e], label=e)
        ax.axhline(D.T[n], ls="--", c="k", lw=1)
        ax.set_yscale("log"); ax.set_xlim(0, nseed); ax.grid(alpha=.3)
        ax.set_title(f"N = {n}, ρ = {PCT[r]}%")
        ax.set_xlabel("Số đề đã giải"); ax.set_ylabel("Thời gian tổng (s)")
    for ax in axl[len(panels):]:
        ax.set_visible(False)
    axl[0].legend(fontsize=8)
    fig.suptitle("Biểu đồ cactus (nét đứt: timeout T)")
    save_fig(fig, path)


# ------------------------------------------------------------------ main
def main():
    csv_path = sys.argv[1] if len(sys.argv) > 1 else "results_raw.csv"
    out = sys.argv[2] if len(sys.argv) > 2 else "analysis_out"
    tdir, fdir = os.path.join(out, "tables"), os.path.join(out, "figures")
    os.makedirs(tdir, exist_ok=True); os.makedirs(fdir, exist_ok=True)

    D = Data(csv_path)
    configure(D)
    print(f"Doc {len(D.df)} luot | hoan tat {len(D.ok)} | timeout {int(D.df.to.sum())} | "
          f"loi {int((D.df.status == 'ERROR').sum())}")
    print(f"Cau hinh co so menh de khong doi giua cac seed (phai = 0 loi): {table_formula_check(D)}")

    tables = {}
    for n, num in zip(NS, ["4.2", "4.3", "4.4", "4.5"]):
        tables[f"Bảng {num}: kết quả Sudoku {n}x{n}"] = (f"tab4_{num[-1]}_results_{n}", table_results(D, n))
    tables["Bảng 4.6: thành phần thời gian N=36, ρ=30%"] = ("tab4_6_cost", table_cost(D))
    tables["Bảng 4.7: tỉ trọng bộ giải Sol/Total (%)"] = ("tab4_7_share", table_share(D))
    tables["Bảng 4.7b: phân vùng hiệu năng (I/II/III)"] = ("tab4_7b_zones", table_zones(D))
    fr_df, FR = table_friedman(D)
    tables["Bảng 4.8: Friedman và hạng trung bình"] = ("tab4_8_friedman", fr_df)
    tables["Bảng 4.9: số đề theo số mã hóa timeout (N=36)"] = ("tab4_9_overlap", table_overlap(D))
    tables["Bảng 4.10: công sức tìm kiếm trên tập seed cùng giải được"] = ("tab4_10_paired", table_paired(D))
    tables["Bảng A1: Fisher–Holm trên số timeout so với Binomial"] = ("tabA1_fisher", table_fisher(D))
    tables["Bảng A2: độ nhạy theo hệ số phạt PAR-k (N=36, ρ=60%)"] = ("tabA2_park", table_par_k(D))
    tables["Bảng A3: regret theo PAR-2 so với mã hóa tốt nhất mỗi ô"] = ("tabA3_regret", table_regret(D))

    md = ["# Bảng và hình Chương 4 (sinh từ results_raw.csv)\n"]
    for title, (fname, df) in tables.items():
        if df.empty:
            continue
        df.to_csv(os.path.join(tdir, fname + ".csv"), index=False)
        md += [f"## {title}\n", md_table(df), ""]
    with open(os.path.join(out, "report.md"), "w", encoding="utf-8") as f:
        f.write("\n".join(md))

    fig_bar(D, "cls", ORDER, "Số mệnh đề (thang log)",
            "Số mệnh đề theo phương pháp và kích thước (ρ = 50%)", os.path.join(fdir, "fig4_1_clauses.png"))
    fig_bar(D, "aux", ORDER[1:], "Số biến phụ (thang log)",
            "Số biến phụ theo phương pháp và kích thước (ρ = 50%)", os.path.join(fdir, "fig4_2_aux.png"))
    fig_par2(D, os.path.join(fdir, "fig4_3_par2_vs_rho.png"))
    fig_cactus(D, os.path.join(fdir, "fig4_4_cactus.png"))

    fcells = [(n, r) for n in NS for r in RS if n >= 16 and (n, r) in FR and
              zone_of([D.cells[(n, r, e)]["share"] for e in ORDER]) != "III (tìm kiếm)"]
    if fcells:
        print(f"Friedman p lon nhat o vung I va II (N>=16, {len(fcells)} o): "
              f"{max(FR[c]['p'] for c in fcells):.2e}")
    prose_numbers(D)
    print(f"\nPAR-k (N=36, rho=60%):\n{table_par_k(D).round(2).to_string()}")
    print(f"\nRegret:\n{table_regret(D).round(2).to_string()}")
    print(f"\nDa ghi: {tdir}/ ({len(tables)} bang), {fdir}/ (4 hinh PNG + PDF), {out}/report.md")


if __name__ == "__main__":
    main()
