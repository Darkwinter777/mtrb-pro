"""Pemeriksa independen mesin SMC Gold.

Membaca candle yang diekspor script MTRB_SMC_Scan (MTRB_Pro_smcscan_bars_<TF>.csv),
mendeteksi ulang semua pola dengan aturan yang sama (ditulis ulang di Python, tidak
memakai kode MQL5), lalu membandingkan hasilnya dengan MTRB_Pro_smcscan_zones.csv.

Kalau semua cocok, kode MQL5 menjalankan aturan yang tertulis. Ini mengecek
kebenaran teknis deteksi, BUKAN profit strategi.

  python smc_check.py --data "<folder Common\\Files>"
  python smc_check.py --bars-m15 a.csv --bars-m5 b.csv     (hanya deteksi + statistik)
"""
import argparse
import csv
import os
from collections import Counter
from datetime import datetime, timezone

OB, RBR, RBS, FVG, IFVG = range(5)
DET, CONF, VALID, MIT, INV, EXP = range(6)
ST = ["DETECTED", "CONFIRMED", "VALID", "MITIGATED", "INVALIDATED", "EXPIRED"]
TFS = {0: "M15", 1: "M5"}
PERIOD = {0: 900, 1: 300}

P = dict(atr=14, fvg_min=0.10, fvg_disp=0.0, ifvg_on=True, ifvg_break=0.10, ifvg_retest=12,
         ob_disp=1.0, ob_bos=10, ob_search=4, ob_wicks=True, imp=0.8, base_rng=0.6, base_tot=1.0,
         depart=0.8, base_max=3, pivot=3, rbs_touch=2, rbs_retest=16, rbs_look=120, rbs_tol=0.25,
         rbs_break=0.20, inval=0.0, max_touch=2, exp=(96, 48))


def pat(t, d):
    return {OB: "OB", RBR: "RBR" if d == 1 else "DBD", RBS: "RBS" if d == 1 else "SBR", FVG: "FVG"}.get(t, "iFVG")


def stamp(ts):
    return datetime.fromtimestamp(ts, timezone.utc).strftime("%Y%m%d%H%M")


def reserve(p):
    return p["atr"] + max(max(p["ob_bos"], p["base_max"] + 2), 2 * p["pivot"] + 1) + 3


class Book:
    def __init__(self):
        self.z = []
        self.lv = []

    def new(self, t, d, tfi, hi, lo, atr, t0, tdet, st):
        for z in self.z:
            if z["type"] == t and z["dir"] == d and z["tfi"] == tfi and z["t0"] == t0:
                return
        self.z.append(dict(id=f"{pat(t, d)}_{TFS[tfi]}_{'B' if d == 1 else 'S'}_{stamp(t0)}", type=t, dir=d, tfi=tfi,
                           hi=hi, lo=lo, atr=atr, t0=t0, tdet=tdet, tconf=tdet if st == VALID else 0,
                           status=st, touches=0, age=0, inside=False))


def atr_at(r, i, n, per):
    if per <= 0 or i + per >= n:
        return 0.0
    return sum(max(r[k][2], r[k + 1][4]) - min(r[k][3], r[k + 1][4]) for k in range(i, i + per)) / per


def process(b, r, n, i, tfi, mask, p):
    """Port langsung SgProcess. r = daftar candle urut series (0 = terbaru): (time, open, high, low, close)."""
    atr = atr_at(r, i, n, p["atr"])
    if atr <= 0:
        return
    t, o, h, l, c = r[i]
    nz = len(b.z)
    for k in range(nz):
        z = b.z[k]
        if z["tfi"] != tfi or z["tdet"] >= t or z["status"] in (INV, EXP):
            continue
        d, ty, zh, zl, za = z["dir"], z["type"], z["hi"], z["lo"], z["atr"]
        ov = l <= zh and h >= zl
        z["age"] += 1
        if z["status"] == DET:
            bad = (c < zl - p["inval"] * za) if d == 1 else (c > zh + p["inval"] * za)
            if bad:
                z["status"] = INV
                continue
            edge = (zh if d == 1 else zl) if ty == IFVG else (zh + zl) / 2.0
            if ov and d * (c - edge) > 0:
                z.update(tconf=t, touches=1, inside=True, age=0, status=CONF)
                continue
            lim = p["ifvg_retest"] if ty == IFVG else p["rbs_retest"]
            if z["age"] > lim:
                z["status"] = EXP
            continue
        brk = zl - c if d == 1 else c - zh
        if brk > p["inval"] * za:
            z["status"] = INV
            if ty == FVG and p["ifvg_on"] and brk >= p["ifvg_break"] * atr:
                b.new(IFVG, -d, tfi, zh, zl, atr, z["t0"], t, DET)
            continue
        if ov and not z["inside"]:
            z["touches"] += 1
            z["inside"] = True
            if z["touches"] > p["max_touch"]:
                z["status"] = EXP
                continue
            if z["status"] != MIT:
                z["status"] = MIT
        elif not ov:
            z["inside"] = False
        if z["age"] > p["exp"][tfi]:
            z["status"] = EXP

    if mask & 4:
        for lv in b.lv:
            if lv["dead"] or lv["tfi"] != tfi:
                continue
            d, px = lv["dir"], lv["px"]
            lv["age"] += 1
            if lv["age"] > p["rbs_look"]:
                lv["dead"] = True
                continue
            if d * (c - px) > p["rbs_break"] * atr:
                lv["dead"] = True
                if lv["touches"] >= p["rbs_touch"]:
                    b.new(RBS, d, tfi, px + p["rbs_tol"] * atr, px - p["rbs_tol"] * atr, atr, lv["t"], t, DET)
                continue
            near = (h >= px - p["rbs_tol"] * atr) if d == 1 else (l <= px + p["rbs_tol"] * atr)
            if near and not lv["inside"]:
                lv["touches"] += 1
                lv["inside"] = True
            elif not near:
                lv["inside"] = False
        j = i + p["pivot"]
        if j + p["pivot"] < n:
            ph = all(r[j - q][2] < r[j][2] and r[j + q][2] < r[j][2] for q in range(1, p["pivot"] + 1))
            pl = all(r[j - q][3] > r[j][3] and r[j + q][3] > r[j][3] for q in range(1, p["pivot"] + 1))
            for s, ok in ((0, ph), (1, pl)):
                if ok:
                    b.lv.append(dict(px=r[j][2] if s == 0 else r[j][3], t=r[j][0], dir=1 if s == 0 else -1, tfi=tfi,
                                     touches=1, age=p["pivot"], inside=False, dead=False))

    if mask & 8 and i + 2 < n:
        body2 = r[i + 1][4] - r[i + 1][1]
        gu, gd = l - r[i + 2][2], r[i + 2][3] - h
        if gu >= p["fvg_min"] * atr and gu > 0 and (p["fvg_disp"] <= 0 or body2 >= p["fvg_disp"] * atr):
            b.new(FVG, 1, tfi, l, r[i + 2][2], atr, r[i + 1][0], t, VALID)
        if gd >= p["fvg_min"] * atr and gd > 0 and (p["fvg_disp"] <= 0 or -body2 >= p["fvg_disp"] * atr):
            b.new(FVG, -1, tfi, r[i + 2][3], h, atr, r[i + 1][0], t, VALID)

    if mask & 1 and i + p["ob_bos"] < n:
        for d in (1, -1):
            body = d * (c - o)
            if body < p["ob_disp"] * atr:
                continue
            ext = r[i + 1][2] if d == 1 else r[i + 1][3]
            for q in range(i + 2, i + p["ob_bos"] + 1):
                ext = max(ext, r[q][2]) if d == 1 else min(ext, r[q][3])
            if d * (c - ext) <= 0:
                continue
            k = next((q for q in range(i + 1, min(i + p["ob_search"], n - 1) + 1) if d * (r[q][4] - r[q][1]) < 0), -1)
            if k < 0:
                continue
            zh = r[k][2] if p["ob_wicks"] else max(r[k][1], r[k][4])
            zl = r[k][3] if p["ob_wicks"] else min(r[k][1], r[k][4])
            b.new(OB, d, tfi, zh, zl, atr, r[k][0], t, VALID)

    if mask & 2:
        for d in (1, -1):
            dep = d * (c - o)
            if dep < p["depart"] * atr:
                continue
            for bb in range(1, p["base_max"] + 1):
                L = i + bb + 1
                if L >= n:
                    break
                base = r[i + 1:i + bb + 1]
                if any(x[2] - x[3] > p["base_rng"] * atr for x in base):
                    break
                bh, bl = max(x[2] for x in base), min(x[3] for x in base)
                if bh - bl > p["base_tot"] * atr:
                    break
                if (d == 1 and c <= bh) or (d == -1 and c >= bl):
                    break
                if d * (r[L][4] - r[L][1]) < p["imp"] * atr:
                    continue
                b.new(RBR, d, tfi, bh, bl, atr, r[i + bb][0], t, VALID)
                break


def read_bars(path):
    with open(path, newline="", encoding="utf-8-sig") as f:
        rows = [(int(x["time"]), float(x["open"]), float(x["high"]), float(x["low"]), float(x["close"])) for x in csv.DictReader(f)]
    return rows[::-1]          # urut series: indeks 0 = candle terbaru


def run(bars):
    b = Book()
    res = reserve(P)
    for tfi, r in bars.items():
        n = len(r)
        mask = (1 | 2 | 4) if tfi == 0 else (8 | 1 | 2)
        for i in range(n - 1 - res, 0, -1):
            process(b, r, n, i, tfi, mask, P)
    return b


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--data")
    ap.add_argument("--bars-m15")
    ap.add_argument("--bars-m5")
    a = ap.parse_args()
    if a.data:
        f15 = os.path.join(a.data, "MTRB_Pro_smcscan_bars_M15.csv")
        f5 = os.path.join(a.data, "MTRB_Pro_smcscan_bars_M5.csv")
    else:
        f15, f5 = a.bars_m15, a.bars_m5
    b = run({0: read_bars(f15), 1: read_bars(f5)})
    cnt = Counter((pat(z["type"], z["dir"]) + " " + TFS[z["tfi"]], ST[z["status"]]) for z in b.z)
    print(f"Python: {len(b.z)} zona")
    for k in sorted({k[0] for k in cnt}):
        print(f"  {k:9s} " + ", ".join(f"{s} {cnt[(k, s)]}" for s in ST if cnt[(k, s)]))
    if not a.data:
        return
    zf = os.path.join(a.data, "MTRB_Pro_smcscan_zones.csv")
    with open(zf, newline="", encoding="utf-8-sig") as f:
        mq = {x["id"]: x for x in csv.DictReader(f)}
    py = {z["id"]: z for z in b.z}
    only_mq = sorted(set(mq) - set(py))
    only_py = sorted(set(py) - set(mq))
    diff = []
    for zid in sorted(set(mq) & set(py)):
        m, z = mq[zid], py[zid]
        if (abs(float(m["zone_lo"]) - z["lo"]) > 1e-4 or abs(float(m["zone_hi"]) - z["hi"]) > 1e-4
                or int(m["t_detect"]) != z["tdet"] or m["status"] != ST[z["status"]] or int(m["touches"]) != z["touches"]):
            diff.append((zid, f"MQL5 {m['zone_lo']}-{m['zone_hi']} {m['status']} sentuh {m['touches']} | "
                              f"Python {z['lo']:.5f}-{z['hi']:.5f} {ST[z['status']]} sentuh {z['touches']}"))
    same = len(set(mq) & set(py)) - len(diff)
    print(f"\nMQL5: {len(mq)} zona. Sama persis: {same}. Beda isi: {len(diff)}. Hanya di MQL5: {len(only_mq)}. Hanya di Python: {len(only_py)}.")
    for zid, why in diff[:10]:
        print("  beda   ", zid, why)
    for zid in only_mq[:10]:
        print("  MQL5   ", zid)
    for zid in only_py[:10]:
        print("  Python ", zid)
    print("\nHASIL:", "COCOK" if not diff and not only_mq and not only_py else "TIDAK COCOK, periksa daftar di atas")


if __name__ == "__main__":
    main()
