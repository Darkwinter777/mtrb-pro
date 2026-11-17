# MTRB Pro v3.08: mesin SMC Gold (audit, desain, validasi)

Dokumen ini menjelaskan mesin SMC Gold (zona M15 + konfirmasi M5) yang ditambahkan ke MTRB Pro v3.08: apa yang dideteksi, kenapa sebuah entry diambil atau ditolak, dan bagaimana mengujinya.

**Status: mati sebagai bawaan (`InpEnableSMCG = false`).** Simulasi 30 hari dengan setelan bawaan rugi (lihat bagian 9). Deteksi pola sudah bisa diaudit; profit belum terbukti.

## 1. File

| File | Isi |
|---|---|
| `MTRB_Pro.mq5` | EA utama v3.08. Hanya disambungkan ke mesin baru (daftar di bagian 4). |
| `MTRB_SMC_Core.mqh` | Inti deteksi pola. Tidak bergantung ke EA, dipakai juga oleh script validasi. |
| `MTRB_SMC.mqh` | Mesin: input, validator confluence, eksekusi, gambar zona, panel debug, log. |
| `MTRB_SMC_Scan.mq5` | Script validasi: menjalankan inti deteksi di histori chart dan mengekspor zona ke CSV. |
| `analysis/smc_check.py` | Pemeriksa independen: deteksi ulang di Python lalu dibandingkan dengan hasil MQL5. |
| `backup/MTRB_Pro_v307.mq5` | Cadangan EA sebelum perubahan ini. |

Untuk compile sendiri, ketiga file `MTRB_Pro.mq5`, `MTRB_SMC.mqh`, dan `MTRB_SMC_Core.mqh` harus berada di folder yang sama (`MQL5\Experts\MTRB Pro\`).

## 2. Audit EA sebelum perubahan (v3.07)

### Arsitektur
- Satu EA, 14 mesin, masing-masing dengan magic sendiri di akun hedging.
- Mesin tambahan masuk lewat `OpenStrategy()`. Fungsi ini menangani:
  - pause dari dashboard, sesi, pemisahan sesi, dan aturan dari halaman Analisa
  - filter volume, batas rugi harian, SL min/max per trade
  - batas total risiko, margin, dan lot `InpLot` (0,01)
- Strategi utama memakai `OpenOne()` langsung, jadi melewati semua gerbang di atas.
- Keluar posisi: aturan bawaan tiap mesin, `TrailStrategies()`, dan `ExitManage()` (TP global: tetap, trailing, atau pindah SL).

### Modul SMC lama (`StrategySMC`, magic 772104)
- Satu timeframe (M15). Alurnya: sweep likuiditas, displacement + FVG, MSS, OB, lalu menunggu harga kembali.
- Hasil uji lama: rugi atau impas di semua variasi. Modul ini tidak diubah dan tetap mati.

### Bug dan risiko yang ditemukan

| # | Lokasi | Masalah | Status |
|---|---|---|---|
| 1 | `SmcDetect` | Kalau tidak ada candle berlawanan sebelum displacement, candle sweep dipakai sebagai OB. Candle sembarang jadi OB. | Tidak diubah (modul lama mati). Mesin baru menolak OB tanpa candle berlawanan. |
| 2 | `StrategySMC` | Tren D1 dibaca dari EMA dan close candle D1 yang masih berjalan (shift 0), jadi bisa berubah sepanjang hari (repaint). | Tidak diubah. Mesin baru hanya memakai candle tertutup. |
| 3 | `StrategySMC` | Saat zona tersentuh tapi entry ditolak (spread, news), setup dibuang tanpa catatan. | Tidak diubah. Mesin baru mencatat setiap penolakan. |
| 4 | `StrategySMC` | Hanya satu setup disimpan, setup baru menimpa yang lama, tanpa ID. | Mesin baru: semua zona punya ID unik. |
| 5 | Antar mesin | Mesin berbeda bisa membuka posisi berlawanan arah bersamaan. | Mesin baru punya penjaga `InpSgNoOpposite`. Mesin lama tidak diubah. |
| 6 | Strategi utama | `OpenOne()` melewati gerbang `OpenStrategy()`. | Dicatat saja, tidak diubah. |
| 7 | `ToWib()` | Selisih jam server dihitung dari waktu sekarang, jadi waktu trade lama bisa meleset 1 jam setelah pergantian DST. | Dicatat saja. |
| 8 | Pencatat trade | MFE/MAE ikut menghitung bagian candle M1 sebelum entry, jadi sedikit terlalu besar. | Dicatat saja. |

## 3. Desain mesin SMC Gold

```
MTRB_SMC_ENGINE (MTRB_SMC.mqh)
|-- inti deteksi (MTRB_SMC_Core.mqh): SgProcess per candle tertutup
|   |-- M15: OB, RBR/DBD, RBS/SBR (level pivot)
|   |-- M5 : FVG, iFVG, OB, RBR/DBD
|-- sinkronisasi M15/M5 (SgSync)
|-- validator confluence (SgFind, SgEvaluate)
|-- eksekusi (SgExecute -> OpenStrategy milik EA)
|-- gambar zona + penanda entry (SgDrawZones, SgDrawEntry)
|-- panel debug (SgPanel) dan log CSV (SgLog)
```

### Integritas data
- **Candle tertutup saja.** Hanya candle tertutup (shift ≥ 1) yang diproses, dari lama ke baru. Saat candle `i` diproses, hanya candle `i` dan yang lebih lama yang dibaca.
- **Urutan proses saat candle M5 baru buka:** candle M15 yang sudah tutup diproses dulu, baru candle M5. Jadi zona M15 yang dipakai di M5 hanya berasal dari candle M15 yang sudah tutup.
- **Tidak ada sinyal sementara di tengah candle.** Keputusan hanya diambil saat candle M5 tutup.
- **Saat EA mulai:** 300 candle histori per timeframe diproses tanpa entry dan tanpa log. Entry baru boleh mulai candle M5 berikutnya.
- **ATR dihitung dari candle itu sendiri** (rata-rata true range 14 candle), bukan dari indikator. Hasilnya sama di EA, script, dan Python.
- **ID sinyal** = pola + timeframe + arah + waktu candle jangkar (contoh `OB_M5_B_202611171015`).
  - Satu zona hanya bisa menghasilkan satu entry.
  - ID yang sudah dipakai disimpan di GlobalVariable `MTRB_sgu_<id>`, jadi tetap terkunci setelah restart.
- **Status zona hanya berubah lewat aturan di `SgProcess`.** Setiap perubahan dicatat dengan alasan.
- **Harga:** semua jarak memakai kelipatan ATR dan harga, bukan point, sehingga tidak bergantung pada digit broker.

## 4. Perubahan di `MTRB_Pro.mq5`
- Versi 3.08.
- `N_ENG` 15. Mesin `SMCG` (magic `InpMagic + 117` = 772117, komentar "MTRB SMCG") ditambahkan di:
  - `DashAdd`, `EngEnabled`, `EngStatus`, `EngSet`
  - `IsOurMagic`, rantai jenis laporan, `EngTF`
  - `EngReversal`: filter volume memperlakukan mesin ini sebagai mesin pembalikan
- Pemanggilan: `SgInit()` di OnInit, `SgDeinit()` di OnDeinit, `StrategySMCG()` di OnTick.
- `#include "MTRB_SMC.mqh"` di akhir file.
- Dashboard: daftar mesin di `api.php`, keterangan di `index.html`.
- Tidak ada perubahan pada lot, risiko, SL/TP, trailing, break-even, atau mesin lain.

## 5. Algoritma deteksi

Semua angka di bawah adalah nilai bawaan dan bisa diubah lewat input.
- **ATR** = ATR timeframe pola pada candle yang sedang diproses.
- **Penulisan candle:** candle 1 = paling lama.

### Siklus hidup zona (semua pola)
- **INVALIDATED:** close menembus sisi seberang zona lebih dari `InpSgInvalAtr` × ATR (bawaan 0). Zona buy batal kalau close di bawah low zona; zona sell kalau close di atas high zona.
- **MITIGATED:** candle masuk zona. Setiap kali masuk lagi setelah sempat keluar dihitung sebagai sentuhan baru.
- **EXPIRED** kalau salah satu terjadi:
  - sentuhan melebihi `InpSgMaxTouches` (2)
  - umur lebih dari 96 candle M15 atau 48 candle M5
  - untuk iFVG/RBS: retest tidak datang dalam batas waktu

### FVG (M5)
- **Bullish:** low candle 3 > high candle 1. Zona = high candle 1 sampai low candle 3.
- **Bearish:** high candle 3 < low candle 1. Zona = high candle 3 sampai low candle 1.
- **Syarat:** lebar gap ≥ 0,10 ATR. Badan candle tengah minimal bisa diatur (bawaan mati).
- **Status awal:** VALID saat candle 3 tutup.

### iFVG (M5)
- **DETECTED:** FVG yang sudah ada menjadi INVALIDATED oleh close yang menembus sisi seberangnya sejauh ≥ 0,10 ATR. Zonanya sama, arahnya dibalik (FVG bullish yang jebol menjadi iFVG bearish).
- **CONFIRMED:** dalam 12 candle, ada candle yang masuk zona lalu menutup di sisi peran barunya (iFVG bearish: close di bawah low zona).
- **INVALIDATED:** sebelum retest, close kembali menembus zona ke arah lama.
- **EXPIRED:** tidak ada retest dalam 12 candle.
- Hanya iFVG yang sudah CONFIRMED yang dihitung hadir. FVG yang jebol tanpa retest tidak pernah dianggap iFVG.

### Order Block (M15 dan M5, terpisah)
- **Displacement:** candle searah dengan badan ≥ 1,0 ATR.
- **BOS:** close displacement melewati high tertinggi (buy) atau low terendah (sell) dari 10 candle sebelumnya.
- **OB:** candle berlawanan arah terakhir dalam 4 candle sebelum displacement. Zona = high-low candle itu (atau badannya saja kalau `InpSgObWicks = false`).
- **Tidak ada candle berlawanan berarti tidak ada OB.** BOS tetap dicatat sebagai konteks M15 di panel.

### RBR / DBD (M15 dan M5)
- **Departure:** candle `i` searah, badan ≥ 0,8 ATR, close melewati ujung base (RBR: di atas high base; DBD: di bawah low base).
- **Base:** 1 sampai 3 candle sebelum departure. Tiap candle range-nya ≤ 0,6 ATR, total lebar base ≤ 1,0 ATR.
- **Leg-in:** candle sebelum base, searah, badan ≥ 0,8 ATR.
- **Zona** = high dan low base. Jumlah base terpendek yang memenuhi syarat yang dipakai.

### RBS / SBR (M15)
- **Level:** swing high (untuk RBS) atau swing low (untuk SBR), yaitu high/low yang lebih ekstrem dari 3 candle di kiri dan 3 di kanan.
  - Level baru diketahui 3 candle setelah pivot. Ini disengaja, supaya tidak memakai data masa depan.
- **Sentuhan level:** high candle mencapai level − 0,25 ATR tanpa breakout. Pivot sendiri dihitung 1.
- **Breakout:** close menembus level lebih dari 0,20 ATR.
  - Kalau sentuhan ≥ 2, zona RBS terbentuk dengan status DETECTED. Zona = level ± 0,25 ATR.
  - Kalau sentuhan kurang, level dibuang.
- **Retest diterima (CONFIRMED):** dalam 16 candle, ada candle yang masuk zona lalu menutup di atas level (SBR: di bawah level).
- **Batal:** close kembali ke bawah zona (INVALIDATED), atau retest tidak datang (EXPIRED).
- **Umur level:** paling lama 120 candle.

## 6. Logika BUY dan SELL

Keputusan dievaluasi sekali per candle M5 tertutup, untuk BUY dan SELL terpisah.

**Pola per arah:**

| Pola | Peran bawaan BUY | Peran bawaan SELL |
|---|---|---|
| OB M15 | OB bullish, opsional | OB bearish, opsional |
| RBR/DBD M15 | RBR, opsional | DBD, opsional |
| RBS/SBR M15 | RBS, opsional | SBR, opsional |
| FVG M5 | bullish, opsional | bearish, opsional |
| iFVG M5 | bullish, opsional | bearish, opsional |
| OB M5 | bullish, **wajib** | bearish, **wajib** |
| RBR/DBD M5 | RBR, tidak dipakai | DBD, opsional |

**Kapan sebuah pola dihitung "hadir":**
- **Pola M15:** zonanya masih dipakai (VALID, CONFIRMED, atau MITIGATED) dan candle M5 terakhir bersinggungan dengan zona. Untuk RBS/SBR ada toleransi 0,5 ATR.
- **Pola M5:** zonanya masih dipakai dan terdeteksi dalam 24 candle M5 terakhir.

**Urutan pengecekan.** Syarat pertama yang gagal menjadi alasan penolakan:
1. Arah dimatikan di input.
2. `InpSgNeedHtfZone`: harga tidak berada di zona M15 mana pun yang dipakai.
3. Ada pola wajib yang belum hadir.
4. Syarat mode tidak terpenuhi:
   - mode 0: semua pola yang dipakai harus hadir
   - mode 1: jumlah pola opsional M5 yang hadir ≥ `InpSgMinOptional`
   - mode 2: skor (bobot pola hadir ÷ bobot pola dipakai × 100) ≥ `InpSgMinScore`
5. Zona entry tidak ada: OB M5 (bawaan), FVG/iFVG M5, atau zona M5 terbaru.
6. Zona entry ini sudah pernah dipakai.
7. Trigger belum terjadi:
   - bawaan: candle M5 masuk zona entry lalu menutup keluar searah entry (BUY: close di atas high zona)
   - opsi lain: cukup menyentuh zona
8. Kalau BUY dan SELL lolos bersamaan, keduanya ditolak.
9. Gerbang eksekusi: akhir pekan, spread > 0,40, news, posisi SMC Gold sudah penuh, posisi EA lain berlawanan arah, SL terlalu dekat, atau SL > 4 ATR.
10. Gerbang risiko EA di `OpenStrategy`.

**SL dan TP:**
- **SL** = balik zona entry M5 + 0,3 ATR M5. Opsi: balik zona M15 yang hadir.
- **TP** = 2 × jarak SL.
- Setelah itu tetap berlaku SL min/max dan TP global milik EA.

## 7. Input baru

### Grup "Strategi: SMC Gold"
| Input | Bawaan | Arti |
|---|---|---|
| `InpEnableSMCG` | false | Nyalakan mesin. Bisa juga dari dashboard. |
| `InpSgBuy` / `InpSgSell` | true | Izinkan arah BUY / SELL. |
| `InpSgHTF` / `InpSgLTF` | M15 / M5 | Timeframe zona dan timeframe entry. |
| `InpSgScanBars` | 300 | Candle histori yang diproses saat mulai. |
| `InpSgMode` | 1 | Mode confluence: 0 semua wajib, 1 wajib + opsional, 2 skor. |
| `InpSgMinOptional` | 1 | Mode 1: minimal pola opsional M5 yang hadir. |
| `InpSgMinScore` | 60 | Mode 2: skor minimal. |
| `InpSgNeedHtfZone` | true | Harga wajib berada di salah satu zona M15 yang dipakai. |
| `InpSgBuy*` / `InpSgSell*` | lihat tabel bagian 6 | Peran tiap pola per arah: 0 tidak dipakai, 1 opsional, 2 wajib. |
| `InpSgW_*` | 20/15/15/15/15/20/10 | Bobot skor tiap pola untuk mode 2. |
| `InpSgLtfMaxAge` | 24 | Pola M5 dihitung hadir kalau umurnya ≤ N candle. |
| `InpSgRbsNearAtr` | 0,5 | Toleransi jarak harga ke zona RBS/SBR (× ATR). |
| `InpSgEntryZone` | 0 | Zona entry: 0 OB M5, 1 FVG/iFVG M5, 2 zona M5 terbaru. |
| `InpSgTrigger` | 1 | Trigger: 0 sentuh zona, 1 candle masuk zona lalu close keluar searah. |
| `InpSgSLMode` | 0 | SL: 0 balik zona entry M5, 1 balik zona M15 yang hadir. |
| `InpSgSLBufAtr` | 0,3 | Jarak SL di balik zona (× ATR M5). |
| `InpSgMaxSLAtr` | 4 | Tolak entry kalau SL lebih jauh dari ini (× ATR M5). |
| `InpSgRR` | 2 | TP = SL × ini. |
| `InpSgMaxSpread` | 0,40 | Spread maksimal (USD harga). |
| `InpSgMaxPos` | 1 | Posisi SMC Gold maksimal bersamaan. |
| `InpSgNoOpposite` | true | Tolak entry kalau ada posisi EA lain berlawanan arah. |

### Grup "SMC Gold: definisi pola"
Angka-angka di bagian 5: lebar FVG, tembusan iFVG dan batas retest, displacement OB, jumlah candle BOS dan pencarian OB, impuls/base/departure RBR, pivot/sentuhan/toleransi/breakout/retest/umur RBS, invalidasi, batas sentuhan, umur zona.

### Grup "SMC Gold: tampilan dan log"
| Input | Bawaan | Arti |
|---|---|---|
| `InpSgDraw` | true | Gambar zona di chart. |
| `InpSgDrawFinal` | true | Tetap tampilkan zona yang batal atau kedaluwarsa. |
| `InpSgKeepHours` | 24 | Hapus zona yang sudah selesai setelah N jam. |
| `InpSgPanel` | true | Panel debug di pojok kanan atas. |
| `InpSgLog` | true | Tulis log ke `MTRB_Pro_smclog.csv`. |

## 8. Tampilan, panel, dan log

**Warna kotak zona:**

| Pola | Warna |
|---|---|
| OB M15 | biru |
| RBR M15 | ungu (DBD M15: ungu tua) |
| RBS | oranye (SBR: oranye tua) |
| FVG M5 | hijau (bullish), merah (bearish) |
| iFVG M5 | kuning |
| OB M5 | aqua (bullish), salmon (bearish) |
| DBD M5 | magenta (RBR M5: plum) |

- **Gaya garis:** tebal untuk M15. Garis putus-putus untuk MITIGATED dan untuk yang menunggu retest; garis titik untuk zona yang batal atau kedaluwarsa.
- **Label zona:** pola, timeframe, arah, status.
- **Saat entry:** panah, garis SL, dan garis TP.
- Objek dibuat sekali per ID zona; tiap candle hanya diperbarui.

**Panel debug (pojok kanan atas):**
- spread dan BOS M15 terakhir
- status tiap pola untuk BUY dan SELL: VALID, CONFIRMED, MITIGATED, INVALIDATED, EXPIRED, WAITING, atau NOT_FOUND, beserta zona harganya
- skor, kelengkapan pola wajib, jumlah opsional
- keputusan (SINYAL, ENTRY, TOLAK, WAITING) dan alasannya

**Log `MTRB_Pro_smclog.csv`** (di Common\Files; saat backtest `MTRB_Pro_smclog_tester.csv`):
- `NEW` dan `STATUS`: tiap zona lahir dan tiap perubahan status, dengan alasan.
- `EVAL`: keputusan per arah per candle M5. Hanya ditulis kalau harga berada di zona M15, supaya log tidak banjir.
- Hasil `ENTRY` atau `REJECT` beserta entry, SL, dan TP.

## 9. Compile dan validasi yang sudah dilakukan

- **Compile:** `MTRB_Pro.mq5` 0 error, 0 warning. `MTRB_SMC_Scan.mq5` 0 error, 0 warning.
- **Belum dijalankan:** di Strategy Tester MT5, maupun di chart live.
- **Deteksi ulang di Python** (`smc_check.py`), data 13 Okt – 12 Nov 2026 (2.000 candle M15, 6.000 candle M5, hasil resample data M1). Dalam 30 hari ditemukan 2.154 zona:

  | Pola | Jumlah zona |
  |---|---|
  | FVG M5 | 1.025 |
  | iFVG M5 | 553 |
  | OB M5 | 266 |
  | SBR M15 | 114 |
  | OB M15 | 94 |
  | RBS M15 | 92 |
  | DBD M5 | 5 |
  | RBR M5 | 3 |
  | DBD M15 | 2 |
  | RBR M15 | **0** |

  Artinya definisi RBR/DBD bawaan sangat ketat. Dengan base 0,8 ATR, total base 1,4 ATR, impuls 0,6, dan departure 0,6, muncul 17 RBR M15 dan 22 DBD M15.
- **Simulasi keputusan** dengan setelan bawaan (entry di open candle berikutnya + spread 0,25, tanpa biaya lain):
  - 49 sinyal dalam 30 hari (18 BUY, 31 SELL), sekitar 1,6 per hari
  - 11 TP dan 38 SL, total **−16R**
  - rata-rata jarak SL 9,3 USD harga, sekitar 9,3 USD rugi per trade di lot 0,01
  - dengan RBR/DBD dilonggarkan: 55 sinyal, total −13R
  - alasan penolakan terbanyak: harga tidak di zona M15, lalu OB M5 belum ada
- Simulasi ini memakai port Python dari aturan yang sama. Ini bukan backtest MT5.

## 10. Cara validasi sendiri

**1. Kebenaran deteksi.** Buka chart XAUUSD, lalu jalankan script `MTRB Pro\MTRB_SMC_Scan` dari Navigator. Setelah itu di terminal:
```bash
python "C:/laragon/www/MTRB Pro/analysis/smc_check.py" --data "%APPDATA%/MetaQuotes/Terminal/Common/Files"
```
Hasil yang diharapkan: `HASIL: COCOK`. Kalau ada beda, script menampilkan ID zona dan isi kedua versi.

**2. Gambar sesuai logika.** Jalankan EA di Strategy Tester mode visual dengan `InpEnableSMCG = true`, lalu bandingkan kotak di chart dengan baris `NEW`/`STATUS` di `MTRB_Pro_smclog_tester.csv`. Setiap kotak harus punya baris `NEW` dengan ID yang sama.

**3. Anotasi manual.** Tandai sendiri 20–30 pola di chart, lalu cocokkan dengan `MTRB_Pro_smcscan_zones.csv`. Ini mengecek apakah definisi di bagian 5 sesuai dengan cara lu membaca chart, terpisah dari apakah kodenya benar.

**4. Hal yang perlu dicek di tester:**

| Yang dicek | Cara memeriksa |
|---|---|
| Sinkronisasi M15/M5 | Tidak ada baris `EVAL` yang memakai zona M15 dengan `t_detect` + 15 menit lebih besar dari waktu candle M5 yang dievaluasi. |
| Tidak ada sinyal ganda | Tiap `signal_id` hanya muncul sekali dengan `ENTRY`. |
| Zona batal tidak dipakai | Tidak ada `ENTRY` dari zona yang sudah INVALIDATED atau EXPIRED di log. |
| SL dan TP | Harga di log sama dengan posisi di tab History tester. |

**5. Profitabilitas.** Backtest "Every tick based on real ticks" minimal 6–12 bulan, dibagi dua periode, sebelum mesin dinyalakan di akun.

## 11. Batasan dan ambiguitas yang belum terjawab

- **Pasangan pola yang tidak disebut di spesifikasi.** Untuk SELL di M15 dipakai OB bearish, DBD M15, dan SBR. Untuk BUY di M5 disediakan RBR M5 (bawaan tidak dipakai). Perannya bisa diubah lewat input.
- **Definisi "resistance".** Dipakai swing pivot dengan minimal 2 sentuhan, bukan zona buatan tangan.
- **BOS untuk OB.** Diukur sebagai close melewati high/low tertinggi N candle, bukan struktur swing yang lebih kompleks (HH/HL).
- **Satu evaluasi per candle M5.** Trigger hanya dinilai saat candle tutup. Tidak ada entry di tengah candle, sehingga harga eksekusi bisa sudah bergerak dari tepi zona.
- **Histori awal 300 candle.** Zona lebih tua dari jendela itu tidak dikenal setelah restart. Sebuah zona juga bisa sedikit berbeda dari versi sebelum restart kalau jendela bergeser tepat di batas pivot.
- **Tidak ada manajemen keluar khusus.** Posisi keluar lewat SL/TP awal dan aturan global EA (`ExitManage`, trailing umum).
- **Filter volume.** Mesin ini dianggap mesin pembalikan oleh filter volume (mode 2).
- **Simulasi rugi.** Hasil −16R berasal dari data satu bulan saat emas sedang reli kuat. Belum ada bukti di periode lain.
