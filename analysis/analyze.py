"""Analisa hasil trade MTRB Pro.

Membaca CSV yang ditulis EA di folder Common\\Files MetaTrader 5:
  MTRB_Pro_history.csv  seluruh riwayat posisi EA (profit, jam, alasan keluar)
  MTRB_Pro_tradelog.csv   kondisi pasar saat entry + MFE/MAE (bahan analisa dan ML)
lalu menulis MTRB_Pro_analysis.json untuk halaman Analisa di dashboard.

Pemakaian:
  python analyze.py --data "<folder Common\\Files>" [--tester]

Rekomendasi hanya saran. Tidak ada setelan yang berubah sampai pengguna menekan
"Terapkan" di dashboard.
"""
import argparse
import json
import math
import os
import sys
import warnings
from datetime import datetime

import numpy as np
import pandas as pd

warnings.filterwarnings("ignore")

TFMT = "%Y.%m.%d %H:%M:%S"
MIN_ENGINE = 30          # minimal trade per mesin sebelum ada saran untuk mesin itu
MIN_ML = 150             # minimal trade bercatatan lengkap sebelum ML dijalankan
TRAIN_FRAC = 0.7         # 70% data lama untuk mencari pola, 30% data terbaru untuk menguji

LABEL = {
    "hour_wib": "jam WIB", "dow": "hari", "mode": "mode Extreme", "spread": "spread",
    "sl_dist": "jarak SL", "tp_dist": "jarak TP", "risk_usd": "risiko di SL", "atr_m5": "ATR M5",
    "atr_h1": "ATR H1", "adx_m15": "ADX M15", "rsi_m5": "RSI M5", "bias_score": "skor bias",
    "flow_buy_pct": "buy % volume", "flow_slope": "arah CVD", "flow_cvd": "CVD", "flow_div": "divergence",
    "flow_absorb": "absorption", "is_buy": "posisi buy",
}
DOW = ["Minggu", "Senin", "Selasa", "Rabu", "Kamis", "Jumat", "Sabtu"]


# ---------------------------------------------------------------- data
def read_csv(path):
    if not os.path.isfile(path) or os.path.getsize(path) == 0:
        return pd.DataFrame()
    try:
        df = pd.read_csv(path)
    except Exception:
        return pd.DataFrame()
    if "close_time_wib" not in df or "profit" not in df:
        return pd.DataFrame()                 # bukan file catatan MTRB Pro
    for c in ("close_time_wib", "open_time_wib"):
        if c in df:
            df[c] = pd.to_datetime(df[c], format=TFMT, errors="coerce")
    df = df.dropna(subset=["close_time_wib"]).sort_values("close_time_wib").reset_index(drop=True)
    return df


def clean(o):
    if isinstance(o, dict):
        return {k: clean(v) for k, v in o.items()}
    if isinstance(o, (list, tuple)):
        return [clean(v) for v in o]
    if isinstance(o, (np.integer,)):
        return int(o)
    if isinstance(o, (np.floating, float)):
        f = float(o)
        return None if math.isnan(f) or math.isinf(f) else round(f, 4)
    if isinstance(o, (np.bool_,)):
        return bool(o)
    return o


# ---------------------------------------------------------------- statistik
def stats(p):
    p = pd.Series(p, dtype=float).dropna()
    n = len(p)
    if n == 0:
        return {"n": 0}
    win = p[p > 0]
    loss = p[p <= 0]
    gp, gl = win.sum(), loss.sum()
    eq = p.cumsum()
    dd = (eq.cummax().clip(lower=0) - eq).max()
    return {
        "n": n, "winrate": len(win) / n * 100, "pf": (gp / -gl) if gl < 0 else None,
        "expectancy": p.mean(), "total": p.sum(), "avg_win": win.mean() if len(win) else 0.0,
        "avg_loss": loss.mean() if len(loss) else 0.0, "max_dd": dd,
    }


def group_stats(df, key, order=None):
    rows = []
    for k, g in df.groupby(key):
        s = stats(g["profit"])
        s["key"] = k
        rows.append(s)
    if order is not None:
        rows.sort(key=lambda r: order(r["key"]))
    return rows


def split(df):
    cut = int(len(df) * TRAIN_FRAC)
    return df.iloc[:cut], df.iloc[cut:]


# ---------------------------------------------------------------- saran
def rec_engines(h, recs):
    for eng, g in h.groupby("engine"):
        if len(g) < MIN_ENGINE:
            continue
        s = stats(g["profit"])
        if s["expectancy"] >= 0 or (s["pf"] is not None and s["pf"] >= 0.8):
            continue
        a, b = split(g)
        ok = a["profit"].sum() < 0 and b["profit"].sum() < 0
        recs.append({
            "id": "off_" + eng, "engine": eng, "kind": "engine",
            "title": f"Matikan mesin {eng}",
            "detail": f"{s['n']} trade, profit factor {s['pf'] or 0:.2f}, rata-rata {s['expectancy']:.2f} per trade.",
            "evidence": "Rugi di data lama dan di data terbaru." if ok else "Rugi secara total, tapi belum konsisten di kedua periode.",
            "confidence": "uji" if ok else "awal", "impact": -s["total"],
            "apply": {"engine": eng, "on": False},
        })


def bad_hours(g):
    base_wr = (g["profit"] > 0).mean() * 100
    out = []
    for hr, x in g.groupby("hour"):
        if len(x) >= 8 and x["profit"].sum() < 0 and (x["profit"] > 0).mean() * 100 <= base_wr - 5:
            out.append(int(hr))
    return sorted(out)


def rec_hours(h, recs):
    for eng, g in h.groupby("engine"):
        if len(g) < MIN_ENGINE:
            continue
        a, b = split(g)
        hrs = bad_hours(a)
        if not hrs:
            continue
        test = b[b["hour"].isin(hrs)]["profit"]
        all_bad = g[g["hour"].isin(hrs)]["profit"]
        if all_bad.sum() >= 0 or len(all_bad) < 5:
            continue
        ok = len(test) >= 5 and test.sum() < 0
        kept = stats(g[~g["hour"].isin(hrs)]["profit"])
        recs.append({
            "id": "hrs_" + eng, "engine": eng, "kind": "hours",
            "title": f"{eng}: jangan entry jam {', '.join(f'{x:02d}' for x in hrs)} WIB",
            "detail": f"{len(all_bad)} trade di jam itu rugi total {all_bad.sum():.2f}. Tanpa jam itu: {kept['n']} trade, total {kept['total']:.2f}.",
            "evidence": "Pola ditemukan di 70% data lama dan tetap rugi di 30% data terbaru." if ok else "Pola baru terlihat di data lama, belum terbukti di data terbaru.",
            "confidence": "uji" if ok else "awal", "impact": -all_bad.sum(),
            "apply": {"blk_" + eng: ",".join(str(x) for x in hrs)},
        })


def rec_spread(lg, recs):
    if "spread" not in lg:
        return
    for eng, g in lg.dropna(subset=["spread"]).groupby("engine"):
        if len(g) < MIN_ENGINE:
            continue
        a, b = split(g)
        best, best_cut = None, 0.0
        for q in (0.5, 0.6, 0.7, 0.8, 0.9):
            t = round(float(a["spread"].quantile(q)), 2)
            hi = a[a["spread"] > t]["profit"]
            if len(hi) >= 5 and hi.sum() < 0 and (best is None or hi.sum() < best_cut):
                best, best_cut = t, hi.sum()
        if best is None:
            continue
        all_hi = g[g["spread"] > best]["profit"]
        if all_hi.sum() >= 0:
            continue
        test = b[b["spread"] > best]["profit"]
        ok = len(test) >= 5 and test.sum() < 0
        recs.append({
            "id": "msp_" + eng, "engine": eng, "kind": "spread",
            "title": f"{eng}: spread maksimal {best:.2f}",
            "detail": f"{len(all_hi)} trade dengan spread di atas {best:.2f} rugi total {all_hi.sum():.2f}.",
            "evidence": "Tetap rugi di data terbaru." if ok else "Belum terbukti di data terbaru.",
            "confidence": "uji" if ok else "awal", "impact": -all_hi.sum(),
            "apply": {"msp_" + eng: best},
        })


def tp_curve(g):
    p = g["profit"].to_numpy(float)
    m = g["mfe_usd"].to_numpy(float)
    grid = np.arange(1.0, 30.01, 0.5)
    tot = [float(np.where(m >= x, x, p).sum()) for x in grid]
    i = int(np.argmax(tot))
    return float(grid[i]), tot[i], float(p.sum())


def tp_section(lg, recs):
    out = {"global": None, "engines": [], "reach": []}
    g = lg.dropna(subset=["mfe_usd"])
    if len(g) == 0:
        return out
    for x in (2, 5, 10, 15, 20):
        out["reach"].append({"usd": x, "pct": float((g["mfe_usd"] >= x).mean() * 100)})
    out["mfe_median"] = float(g["mfe_usd"].median())
    if len(g) >= 10:
        tp, sim, act = tp_curve(g)
        out["global"] = {"n": len(g), "tp": tp, "sim_total": sim, "actual_total": act}
    for eng, x in g.groupby("engine"):
        if len(x) >= 10:
            tp, sim, act = tp_curve(x)
            out["engines"].append({"engine": eng, "n": len(x), "tp": tp, "sim_total": sim, "actual_total": act,
                                   "mfe_median": float(x["mfe_usd"].median())})
    gl = out["global"]
    if gl and gl["n"] >= MIN_ENGINE and gl["sim_total"] - gl["actual_total"] >= max(5.0, abs(gl["actual_total"]) * 0.1):
        a, b = split(g)
        tp_a, _, _ = tp_curve(a)
        bp, bm = b["profit"].to_numpy(float), b["mfe_usd"].to_numpy(float)
        ok = len(b) >= 10 and np.where(bm >= tp_a, tp_a, bp).sum() > bp.sum()
        recs.append({
            "id": "tp_global", "engine": "", "kind": "tp",
            "title": f"Ambil untung tetap di {gl['tp']:.1f}",
            "detail": f"Kalau semua posisi ditutup saat profit {gl['tp']:.1f}, hasil {gl['n']} trade jadi {gl['sim_total']:.2f} (sekarang {gl['actual_total']:.2f}).",
            "evidence": ("TP dari data lama juga lebih baik di data terbaru." if ok else "Belum terbukti di data terbaru.")
                        + " Profit tertinggi dihitung dari candle M1, jadi ini perkiraan.",
            "confidence": "uji" if ok else "awal", "impact": gl["sim_total"] - gl["actual_total"],
            "apply": {"tp_mode": 1, "tp_usd": gl["tp"]},
        })
    return out


def flow_section(lg, recs):
    if "flow_ok" not in lg:
        return None
    g = lg.dropna(subset=["flow_ok"])
    if len(g) == 0:
        return None
    ok_s, bad_s = stats(g[g["flow_ok"] == 1]["profit"]), stats(g[g["flow_ok"] == 0]["profit"])
    out = {"pass": ok_s, "fail": bad_s, "engines": []}
    for eng, x in g.groupby("engine"):
        out["engines"].append({"engine": eng, "pass": stats(x[x["flow_ok"] == 1]["profit"]),
                               "fail": stats(x[x["flow_ok"] == 0]["profit"])})
    if bad_s["n"] >= 15 and bad_s["total"] < 0 and ok_s["n"] >= 15 and ok_s["expectancy"] > bad_s["expectancy"]:
        a, b = split(g)
        bt = b[b["flow_ok"] == 0]["profit"]
        ok = len(bt) >= 5 and bt.sum() < 0
        recs.append({
            "id": "flow_on", "engine": "", "kind": "flow",
            "title": "Nyalakan filter Buy/Sell volume",
            "detail": f"{bad_s['n']} trade yang volumenya tidak mendukung rugi total {bad_s['total']:.2f}; yang didukung rata-rata {ok_s['expectancy']:.2f} per trade.",
            "evidence": "Tetap rugi di data terbaru." if ok else "Belum terbukti di data terbaru.",
            "confidence": "uji" if ok else "awal", "impact": -bad_s["total"],
            "apply": {"flow_mode": 2},
        })
    return out


# ---------------------------------------------------------------- machine learning
def ml_section(lg):
    feat = [c for c in LABEL if c in lg.columns or c == "is_buy"]
    d = lg.dropna(subset=["hour_wib"]).copy() if "hour_wib" in lg else pd.DataFrame()
    if len(d) < MIN_ML:
        return {"status": "kurang_data", "n": len(d), "need": MIN_ML}
    try:
        from sklearn.ensemble import HistGradientBoostingClassifier
        from sklearn.inspection import permutation_importance
        from sklearn.metrics import roc_auc_score
        from sklearn.tree import DecisionTreeRegressor
    except Exception:
        return {"status": "no_sklearn", "n": len(d)}
    d["is_buy"] = (d["side"] == "BUY").astype(int)
    X = d[feat].apply(pd.to_numeric, errors="coerce")
    for eng in sorted(d["engine"].unique()):
        X["mesin=" + eng] = (d["engine"] == eng).astype(int)
    y = (d["profit"] > 0).astype(int)
    cut = int(len(d) * TRAIN_FRAC)
    Xa, Xb, ya, yb = X.iloc[:cut], X.iloc[cut:], y.iloc[:cut], y.iloc[cut:]
    out = {"status": "ok", "n": len(d), "n_train": cut, "n_test": len(d) - cut, "base_winrate": float(y.mean() * 100)}
    if ya.nunique() < 2 or yb.nunique() < 2:
        out["status"] = "satu_kelas"
        return out
    clf = HistGradientBoostingClassifier(max_depth=3, learning_rate=0.05, max_iter=200, min_samples_leaf=15, random_state=7)
    clf.fit(Xa, ya)
    auc = roc_auc_score(yb, clf.predict_proba(Xb)[:, 1])
    out["auc"] = float(auc)
    pi = permutation_importance(clf, Xb, yb, scoring="roc_auc", n_repeats=8, random_state=7)
    imp = sorted(zip(X.columns, pi.importances_mean), key=lambda z: -z[1])
    out["importance"] = [{"feature": LABEL.get(c, c.replace("mesin=", "mesin ")), "imp": float(v)} for c, v in imp[:8] if v > 0]

    # aturan yang bisa dibaca: pohon keputusan kecil pada profit, dicek ulang di data terbaru
    leaf = max(15, int(len(Xa) * 0.05))
    tree = DecisionTreeRegressor(max_depth=3, min_samples_leaf=leaf, random_state=7)
    pa = d["profit"].iloc[:cut]
    pb = d["profit"].iloc[cut:]
    Xa_f, Xb_f = Xa.fillna(-999), Xb.fillna(-999)
    tree.fit(Xa_f, pa)
    la, lb = tree.apply(Xa_f), tree.apply(Xb_f)
    t = tree.tree_
    paths = {}

    def walk(node, conds):
        if t.children_left[node] == -1:
            paths[node] = conds
            return
        name, thr = X.columns[t.feature[node]], t.threshold[node]
        walk(t.children_left[node], conds + [(name, "<=", thr)])
        walk(t.children_right[node], conds + [(name, ">", thr)])
    walk(0, [])
    rules = []
    for node, conds in paths.items():
        ma, mb = pa[la == node], pb[lb == node]
        if len(ma) < leaf or ma.mean() >= 0:
            continue
        rules.append({
            "text": " dan ".join(pretty(c) for c in conds) or "semua trade",
            "n_train": len(ma), "avg_train": float(ma.mean()), "total_train": float(ma.sum()),
            "n_test": len(mb), "avg_test": float(mb.mean()) if len(mb) else None,
            "proven": bool(len(mb) >= 5 and mb.mean() < 0),
        })
    rules.sort(key=lambda r: r["total_train"])
    out["rules"] = rules[:6]
    if auc < 0.55:
        out["verdict"] = "Model belum bisa membedakan trade menang dan kalah lebih baik dari tebakan. Butuh data lebih banyak atau kondisi pasar yang dicatat belum menjelaskan hasil trade."
    elif auc < 0.62:
        out["verdict"] = "Model menemukan pola lemah. Pakai aturan yang terbukti di data terbaru saja."
    else:
        out["verdict"] = "Model menemukan pola yang cukup jelas di data terbaru. Tetap cek ulang setelah ada data baru."
    return out


def pretty(c):
    name, op, thr = c
    if name.startswith("mesin="):
        eng = name[6:]
        return f"mesin {eng}" if op == ">" else f"bukan mesin {eng}"
    lab = LABEL.get(name, name)
    if thr < -500:                                    # pemisah antara nilai kosong (-999) dan nilai asli
        return f"{lab} tidak tercatat" if op == "<=" else f"{lab} tercatat"
    if name in ("is_buy", "mode"):
        yes = op == ">"
        return {"is_buy": "posisi buy" if yes else "posisi sell", "mode": "mode Extreme" if yes else "mode Normal"}[name]
    fl = int(math.floor(thr))
    if name == "hour_wib":
        return f"jam >= {fl + 1:02d} WIB" if op == ">" else f"jam <= {fl:02d} WIB"
    if name == "dow":
        return f"hari sesudah {DOW[min(6, max(0, fl))]}" if op == ">" else f"hari sampai {DOW[min(6, max(0, fl))]}"
    return f"{lab} {op} {thr:.2f}"


# ---------------------------------------------------------------- utama
def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--data", required=True)
    ap.add_argument("--out", default=None)
    ap.add_argument("--tester", action="store_true", help="ikutkan data backtest terakhir")
    a = ap.parse_args()
    out_path = a.out or os.path.join(a.data, "MTRB_Pro_analysis.json")

    hist = read_csv(os.path.join(a.data, "MTRB_Pro_history.csv"))
    lg = read_csv(os.path.join(a.data, "MTRB_Pro_tradelog.csv"))
    if a.tester:
        lt = read_csv(os.path.join(a.data, "MTRB_Pro_tradelog_tester.csv"))
        if len(lt):
            lt["position"] = "T" + lt["position"].astype(str)
            lg = pd.concat([lt, lg], ignore_index=True).sort_values("close_time_wib").reset_index(drop=True)
    base = hist if len(hist) else lg
    res = {"generated": datetime.now().strftime("%Y-%m-%d %H:%M"), "tester": a.tester,
           "counts": {"history": len(hist), "log": len(lg),
                      "log_features": int(lg["hour_wib"].notna().sum()) if "hour_wib" in lg else 0},
           "recs": [], "notes": []}
    if len(base) == 0:
        res["notes"].append("Belum ada trade tertutup yang tercatat. Biarkan EA v3.07 berjalan dulu.")
        json.dump(clean(res), open(out_path, "w", encoding="utf-8"), ensure_ascii=False)
        print("kosong")
        return
    base = base.copy()
    base["hour"] = base["open_time_wib"].dt.hour
    base["dow"] = base["open_time_wib"].dt.dayofweek.map(lambda x: (x + 1) % 7)
    res["period"] = {"from": base["close_time_wib"].min().strftime("%Y-%m-%d"), "to": base["close_time_wib"].max().strftime("%Y-%m-%d")}
    res["summary"] = stats(base["profit"])
    res["engines"] = sorted(group_stats(base, "engine"), key=lambda r: -r["total"])
    res["hours"] = group_stats(base, "hour", order=lambda k: k)
    res["dow"] = [dict(r, key=DOW[int(r["key"])]) for r in group_stats(base, "dow", order=lambda k: k)]
    res["reasons"] = sorted(group_stats(base, "exit_reason"), key=lambda r: -r["n"])
    res["engine_hours"] = {eng: group_stats(g, "hour", order=lambda k: k) for eng, g in base.groupby("engine")}
    res["equity"] = [{"t": t.strftime("%Y-%m-%d %H:%M"), "v": v} for t, v in zip(base["close_time_wib"], base["profit"].cumsum())][-500:]

    recs = res["recs"]
    rec_engines(base, recs)
    rec_hours(base, recs)
    if len(lg):
        lg = lg.copy()
        rec_spread(lg, recs)
        res["tp"] = tp_section(lg, recs)
        res["flow"] = flow_section(lg, recs)
        res["ml"] = ml_section(lg)
        if "session" in lg:
            res["sessions"] = group_stats(lg.dropna(subset=["session"]), "session")
    else:
        res["ml"] = {"status": "kurang_data", "n": 0, "need": MIN_ML}
    recs.sort(key=lambda r: (r["confidence"] != "uji", -r["impact"]))
    if res["summary"]["n"] < 100:
        res["notes"].append(f"Baru {res['summary']['n']} trade. Pola dari data sesedikit ini mudah berubah; anggap saran sebagai petunjuk awal.")
    json.dump(clean(res), open(out_path, "w", encoding="utf-8"), ensure_ascii=False)
    print("ok", res["summary"]["n"], "trade,", len(recs), "saran")


if __name__ == "__main__":
    main()
