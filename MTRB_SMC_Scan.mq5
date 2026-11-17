//+------------------------------------------------------------------+
//| MTRB_SMC_Scan.mq5                                                |
//| Script validasi mesin SMC Gold. Menjalankan inti deteksi yang    |
//| sama persis dengan EA (MTRB_SMC_Core.mqh, parameter bawaan) pada |
//| histori chart, lalu menulis ke Common\Files:                     |
//|   MTRB_Pro_smcscan_bars_<TF>.csv  candle yang diproses           |
//|   MTRB_Pro_smcscan_zones.csv      semua zona + status akhir      |
//|   MTRB_Pro_smcscan_events.csv     tiap perubahan status + alasan |
//| Hasilnya dibandingkan dengan analysis/smc_check.py.              |
//+------------------------------------------------------------------+
#property copyright "MTRB Pro"
#property version   "1.00"
#property script_show_inputs

#include "MTRB_SMC_Core.mqh"

input ENUM_TIMEFRAMES InpHTF  = PERIOD_M15; // Timeframe zona
input ENUM_TIMEFRAMES InpLTF  = PERIOD_M5;  // Timeframe konfirmasi
input int             InpBarsHTF = 2000;    // Jumlah candle M15
input int             InpBarsLTF = 6000;    // Jumlah candle M5

void WriteText(const string name, const string s)
  {
   int h = FileOpen(name, FILE_WRITE | FILE_BIN | FILE_COMMON);
   if(h == INVALID_HANDLE)
     {
      Print("Gagal menulis ", name);
      return;
     }
   uchar b[];
   int len = StringToCharArray(s, b, 0, WHOLE_ARRAY, CP_UTF8);
   if(len > 1)
      FileWriteArray(h, b, 0, len - 1);
   FileClose(h);
  }

void OnStart()
  {
   SgParams p;
   SgDefaults(p);
   g_sgTf[0] = InpHTF;
   g_sgTf[1] = InpLTF;
   ArrayResize(g_sgZ, 0);
   ArrayResize(g_sgL, 0);
   ArrayResize(g_sgEv, 0);
   int res = SgReserve(p);
   for(int tfi = 0; tfi < 2; tfi++)
     {
      MqlRates r[];
      ArraySetAsSeries(r, true);
      int want = (tfi == 0) ? InpBarsHTF : InpBarsLTF;
      int n = CopyRates(_Symbol, g_sgTf[tfi], 0, want, r);
      if(n < res + 20)
        {
         PrintFormat("Data %s kurang: %d candle", SgTfName(tfi), n);
         return;
        }
      string s = "time,open,high,low,close\r\n";
      for(int i = n - 1; i >= 0; i--)
         s += StringFormat("%I64d,%.5f,%.5f,%.5f,%.5f\r\n", (long)r[i].time, r[i].open, r[i].high, r[i].low, r[i].close);
      WriteText("MTRB_Pro_smcscan_bars_" + SgTfName(tfi) + ".csv", s);
      int mask = (tfi == 0) ? (SGM_OB | SGM_RBR | SGM_RBS) : (SGM_FVG | SGM_OB | SGM_RBR);
      for(int i = n - 1 - res; i >= 1; i--)
         SgProcess(r, n, i, tfi, mask, p);
     }
   string z = "id,pattern,dir,tf,t0,t_detect,t_confirm,zone_lo,zone_hi,status,touches,reason\r\n";
   for(int k = 0; k < ArraySize(g_sgZ); k++)
     {
      string why = g_sgZ[k].why;
      StringReplace(why, ",", ";");
      z += StringFormat("%s,%s,%s,%s,%I64d,%I64d,%I64d,%.5f,%.5f,%s,%d,%s\r\n", g_sgZ[k].id, SgPat(g_sgZ[k].type, g_sgZ[k].dir),
                        g_sgZ[k].dir == 1 ? "BUY" : "SELL", SgTfName(g_sgZ[k].tfi), (long)g_sgZ[k].t0, (long)g_sgZ[k].tDet, (long)g_sgZ[k].tConf,
                        g_sgZ[k].lo, g_sgZ[k].hi, SgSt(g_sgZ[k].status), g_sgZ[k].touches, why);
     }
   WriteText("MTRB_Pro_smcscan_zones.csv", z);
   string e = "time_close,event,id,dir,pattern,tf,zone_lo,zone_hi,status,reason\r\n";
   for(int k = 0; k < ArraySize(g_sgEv); k++)
      e += g_sgEv[k] + "\r\n";
   WriteText("MTRB_Pro_smcscan_events.csv", e);
   PrintFormat("[SMC scan] %d zona, %d event. File di Common\\Files. Bandingkan dengan: python analysis/smc_check.py", ArraySize(g_sgZ), ArraySize(g_sgEv));
  }
