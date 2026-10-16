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
NS = [9, 16, 25, 36]
RS = [0.3, 0.4, 0.5, 0.6]
PCT = {r: int(round(r * 100)) for r in RS}


# ------------------------------------------------------------------ thong ke
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


# ------------------------------------------------------------------ du lieu
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
        for c in ["sol_time", "conflicts"]:
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


# ------------------------------------------------------------------ cac bang
def table_results(D, n):
    rows = []
    for r in RS:
        for e in ORDER:
            c = D.cells[(n, r, e)]
            rows.append({
                "rho": f"{PCT[r]}%", "E": c["E"], "G": n * n - c["E"], "Encoding": e,
                "Aux": c["aux"], "Clauses": c["cls"],
                "Enc": c["enc"], "Load": c["load"], "Sol": c["sol"],
                "PAR2": c["par2"], "CI_lo": c["lo"], "CI_hi": c["hi"],
                "Conflicts": c["conf"], "Decisions": c["dec"],
                "Timeouts": f"{c['nto']}/{c['N']}"})
    return pd.DataFrame(rows)


def table_cost(D):
    o = D.ok.assign(enc_us=D.ok.enc_time / D.ok.clauses * 1e6,
                    load_us=D.ok.load_time / D.ok.clauses * 1e6)
    g = o[o.n == 36].groupby("encoding")[["enc_us", "load_us"]].mean()
    rows = []
    for e in ORDER:
        c = D.cells[(36, 0.3, e)]
        rows.append({"Encoding": e, "Clauses": c["cls"], "Enc": c["enc"], "Load": c["load"],
                     "Enc+Load": c["enc"] + c["load"], "Sol": c["sol"], "PAR2": c["par2"],
                     "Enc_us_per_clause": g.enc_us[e], "Load_us_per_clause": g.load_us[e]})
    return pd.DataFrame(rows)


def table_share(D):
    rows = []
    for n in NS:
        for r in RS:
            d = {"N": n, "rho": f"{PCT[r]}%"}
            d.update({e: D.cells[(n, r, e)]["share"] for e in ORDER})
            rows.append(d)
    return pd.DataFrame(rows)


def table_friedman(D):
    rows, FR = [], {}
    for n in NS:
        for r in RS:
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
        St = D.wide(36, r, "status")
        out[f"rho={PCT[r]}%"] = (St == "TIMEOUT").sum(axis=1).value_counts().to_dict()
    return pd.DataFrame({k: [v.get(i, 0) for i in range(6)] for k, v in out.items()},
                        index=pd.Index(range(6), name="k_encodings_timeout")).reset_index()


def table_paired(D):
    rows = []
    for n, r in [(25, 0.5), (25, 0.6), (36, 0.6)]:
        ns, enc, res = D.paired(n, r)
        for e in ORDER:
            m = enc[e]
            d = {"N": n, "rho": f"{PCT[r]}%", "common_seeds": ns, "Encoding": e,
                 "Sol_median": m["sol"]}
            if e == "Binomial":
                d.update({"Sol_x": np.nan, "Sol_p": np.nan, "Conf_x": np.nan, "Conf_p": np.nan})
            else:
                d.update({"Sol_x": res[("sol_time", e)][0], "Sol_p": res[("sol_time", e)][1],
                          "Conf_x": res[("conflicts", e)][0], "Conf_p": res[("conflicts", e)][1]})
            d.update({"Conflicts_median": m["conf"], "Decisions_median": m["dec"],
                      "kconf_per_s": m["kcps"], "Prop_per_conf": m["ppc"]})
            rows.append(d)
    return pd.DataFrame(rows)


def table_formula_check(D):
    """So sanh so menh de/bien phu do duoc giua cac seed (phai khong doi)."""
    g = D.df.dropna(subset=["clauses"]).groupby(["n", "empty_ratio", "encoding"])
    bad = g.clauses.nunique()
    return int((bad > 1).sum())


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


# ------------------------------------------------------------------ hinh
def fig_bar(D, key, encs, ylabel, title, path):
    fig, ax = plt.subplots(figsize=(8, 4.5))
    w = 0.8 / len(encs)
    for i, e in enumerate(encs):
        vals = [D.cells[(n, 0.5, e)][key] for n in NS]
        ax.bar(np.arange(len(NS)) + i * w, vals, w, label=e)
    ax.set_xticks(np.arange(len(NS)) + w * (len(encs) - 1) / 2)
    ax.set_xticklabels([f"{n}x{n}" for n in NS])
    ax.set_yscale("log"); ax.set_ylabel(ylabel); ax.set_xlabel("Kich thuoc Sudoku")
    ax.set_title(title); ax.grid(axis="y", alpha=.3); ax.legend()
    fig.tight_layout(); fig.savefig(path, dpi=200); plt.close(fig)


def fig_par2(D, path):
    fig, axs = plt.subplots(2, 2, figsize=(10, 7))
    for ax, n in zip(axs.ravel(), NS):
        for e in ORDER:
            ax.plot([PCT[r] for r in RS], [D.cells[(n, r, e)]["par2"] for r in RS],
                    marker="o", ms=4, label=e)
        ax.axhline(2 * D.T[n], ls="--", c="k", lw=1)
        ax.set_yscale("log"); ax.set_xticks([30, 40, 50, 60]); ax.grid(alpha=.3)
        ax.set_title(f"N = {n}"); ax.set_xlabel("Ti le o trong rho (%)"); ax.set_ylabel("PAR-2 (s)")
    axs[0, 0].legend(fontsize=8)
    fig.suptitle("PAR-2 theo ti le o trong (net dut: muc phat 2T)")
    fig.tight_layout(); fig.savefig(path, dpi=200); plt.close(fig)


def fig_cactus(D, path):
    panels = [(25, .6), (36, .4), (36, .5), (36, .6)]
    fig, axs = plt.subplots(2, 2, figsize=(10, 7))
    for ax, (n, r) in zip(axs.ravel(), panels):
        sub = D.ok[(D.ok.n == n) & (D.ok.empty_ratio == r)]
        for e in ORDER:
            t = np.sort(sub[sub.encoding == e].total_time.values)
            if len(t):
                ax.plot(np.arange(1, len(t) + 1), t, marker="o", ms=3, label=e)
        ax.axhline(D.T[n], ls="--", c="k", lw=1)
        ax.set_yscale("log"); ax.set_xlim(0, 30); ax.grid(alpha=.3)
        ax.set_title(f"N = {n}, rho = {PCT[r]}%")
        ax.set_xlabel("So de da giai"); ax.set_ylabel("Thoi gian tong (s)")
    axs[0, 0].legend(fontsize=8)
    fig.suptitle("Bieu do cactus (net dut: timeout T)")
    fig.tight_layout(); fig.savefig(path, dpi=200); plt.close(fig)


# ------------------------------------------------------------------ main
def main():
    csv_path = sys.argv[1] if len(sys.argv) > 1 else "results_raw.csv"
    out = sys.argv[2] if len(sys.argv) > 2 else "analysis_out"
    tdir, fdir = os.path.join(out, "tables"), os.path.join(out, "figures")
    os.makedirs(tdir, exist_ok=True); os.makedirs(fdir, exist_ok=True)

    D = Data(csv_path)
    print(f"Doc {len(D.df)} luot | hoan tat {len(D.ok)} | timeout {int(D.df.to.sum())} | "
          f"loi {int((D.df.status == 'ERROR').sum())}")
    print(f"Cau hinh co so menh de khong doi giua cac seed (phai = 0 loi): {table_formula_check(D)}")

    tables = {}
    for n, num in zip(NS, ["4.2", "4.3", "4.4", "4.5"]):
        tables[f"Bang {num}: ket qua Sudoku {n}x{n}"] = (f"tab4_{num[-1]}_results_{n}", table_results(D, n))
    tables["Bang 4.6: thanh phan thoi gian N=36, rho=30%"] = ("tab4_6_cost", table_cost(D))
    tables["Bang 4.7: ti trong bo giai Sol/Total (%)"] = ("tab4_7_share", table_share(D))
    fr_df, FR = table_friedman(D)
    tables["Bang 4.8: Friedman va hang trung binh"] = ("tab4_8_friedman", fr_df)
    tables["Bang 4.9: so de theo so ma hoa timeout (N=36)"] = ("tab4_9_overlap", table_overlap(D))
    tables["Bang 4.10: cong suc tim kiem tren tap seed cung giai duoc"] = ("tab4_10_paired", table_paired(D))

    md = ["# Bang va hinh Chuong 4 (sinh tu results_raw.csv)\n"]
    for title, (fname, df) in tables.items():
        df.to_csv(os.path.join(tdir, fname + ".csv"), index=False)
        md += [f"## {title}\n", md_table(df), ""]
    with open(os.path.join(out, "report.md"), "w", encoding="utf-8") as f:
        f.write("\n".join(md))

    fig_bar(D, "cls", ORDER, "So menh de (thang log)",
            "So menh de theo phuong phap va kich thuoc (rho=50%)", os.path.join(fdir, "fig4_1_clauses.png"))
    fig_bar(D, "aux", ORDER[1:], "So bien phu (thang log)",
            "So bien phu theo phuong phap va kich thuoc (rho=50%)", os.path.join(fdir, "fig4_2_aux.png"))
    fig_par2(D, os.path.join(fdir, "fig4_3_par2_vs_rho.png"))
    fig_cactus(D, os.path.join(fdir, "fig4_4_cactus.png"))

    # tom tat nhanh cac con so hay dung trong van xuoi
    fcells = [(16, r) for r in RS] + [(25, r) for r in RS] + [(36, .3), (36, .4)]
    print(f"Friedman p lon nhat o che do cong thuc (N>=16): {max(FR[c]['p'] for c in fcells):.2e}")
    print(f"Da ghi: {tdir}/ ({len(tables)} bang), {fdir}/ (4 hinh), {out}/report.md")


if __name__ == "__main__":
    main()
