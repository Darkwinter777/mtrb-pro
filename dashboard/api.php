<?php
// API kecil untuk dashboard MTRB Pro: membaca status dari EA dan menulis perintah untuk EA.
$cfg = require __DIR__ . '/config.php';

header('Content-Type: application/json; charset=utf-8');
header('Cache-Control: no-store');

function out($data, $code = 200)
{
    http_response_code($code);
    echo json_encode($data, JSON_UNESCAPED_UNICODE);
    exit;
}

// --- akses: tanpa PIN hanya dari komputer ini; dengan PIN wajib menyertakan PIN yang benar
$ip    = isset($_SERVER['REMOTE_ADDR']) ? $_SERVER['REMOTE_ADDR'] : '';
$local = in_array($ip, ['127.0.0.1', '::1'], true);
$pin   = isset($cfg['pin']) ? (string) $cfg['pin'] : '';
if ($pin === '') {
    if (!$local) {
        out(['ok' => false, 'error' => 'remote_blocked'], 403);
    }
} else {
    $given = isset($_SERVER['HTTP_X_PIN']) ? (string) $_SERVER['HTTP_X_PIN'] : '';
    if (!hash_equals($pin, $given)) {
        out(['ok' => false, 'error' => 'pin'], 401);
    }
}

$dir         = rtrim($cfg['data_dir'], "\\/");
$statusFile  = $dir . DIRECTORY_SEPARATOR . 'MTRB_Pro_status.json';
$controlFile = $dir . DIRECTORY_SEPARATOR . 'MTRB_Pro_control.txt';
$engines     = ['DIP', 'NAO', 'CDL', 'RH', 'HB1', 'HB2', 'HB3', 'TL1', 'TL2', 'ORB', 'RSM', 'MOM', 'SMC', 'MAIN'];
$demo        = !empty($_GET['demo']);

function readControl($file)
{
    $c = [];
    if (is_file($file)) {
        foreach (file($file, FILE_IGNORE_NEW_LINES | FILE_SKIP_EMPTY_LINES) as $ln) {
            $p = strpos($ln, '=');
            if ($p > 0) {
                $c[trim(substr($ln, 0, $p))] = trim(substr($ln, $p + 1));
            }
        }
    }
    return $c;
}

$a = isset($_GET['a']) ? $_GET['a'] : 'status';

if ($a === 'status') {
    if ($demo) {
        $d = json_decode(file_get_contents(__DIR__ . '/sample_status.json'), true);
        out(['ok' => true, 'demo' => true, 'age' => 0, 'data' => $d]);
    }
    if (!is_file($statusFile)) {
        out(['ok' => false, 'error' => 'no_status']);
    }
    $d = null;
    for ($i = 0; $i < 4; $i++) {              // EA mungkin sedang menulis: coba ulang sebentar
        $d = json_decode((string) @file_get_contents($statusFile), true);
        if (is_array($d)) {
            break;
        }
        usleep(60000);
    }
    if (!is_array($d)) {
        out(['ok' => false, 'error' => 'bad_status']);
    }
    clearstatcache();
    out(['ok' => true, 'demo' => false, 'age' => max(0, time() - filemtime($statusFile)), 'data' => $d]);
}

if ($a === 'control') {
    if ($_SERVER['REQUEST_METHOD'] !== 'POST') {
        out(['ok' => false, 'error' => 'method'], 405);
    }
    $in = json_decode((string) file_get_contents('php://input'), true);
    if (!is_array($in)) {
        out(['ok' => false, 'error' => 'bad_request'], 400);
    }
    $c = readControl($controlFile);

    if (isset($in['engine'], $in['on'])) {
        if (!in_array($in['engine'], $engines, true)) {
            out(['ok' => false, 'error' => 'engine'], 400);
        }
        $c[$in['engine']] = $in['on'] ? '1' : '0';
    }
    if (isset($in['paused'])) {
        $c['paused'] = $in['paused'] ? '1' : '0';
    }
    if (isset($in['max_open_risk'])) {
        $v = (float) $in['max_open_risk'];
        if ($v < 0 || $v > 1000000) {
            out(['ok' => false, 'error' => 'max_open_risk'], 400);
        }
        $c['max_open_risk'] = rtrim(rtrim(number_format($v, 2, '.', ''), '0'), '.');
    }
    if (isset($in['daily_loss_pct'])) {
        $v = (float) $in['daily_loss_pct'];
        if ($v < 0 || $v > 100) {
            out(['ok' => false, 'error' => 'daily_loss_pct'], 400);
        }
        $c['daily_loss_pct'] = rtrim(rtrim(number_format($v, 2, '.', ''), '0'), '.');
    }
    foreach (['sess_asia', 'sess_london', 'sess_ny', 'news_filter'] as $key) {
        if (isset($in[$key])) {
            $c[$key] = $in[$key] ? '1' : '0';
        }
    }
    foreach (['sl_min', 'sl_max'] as $key) {
        if (isset($in[$key])) {
            $v = (float) $in[$key];
            if ($v < 0 || $v > 1000000) {
                out(['ok' => false, 'error' => $key], 400);
            }
            $c[$key] = rtrim(rtrim(number_format($v, 2, '.', ''), '0'), '.');
        }
    }
    $mn = isset($c['sl_min']) ? (float) $c['sl_min'] : 0;
    $mx = isset($c['sl_max']) ? (float) $c['sl_max'] : 0;
    if ($mn > 0 && $mx > 0 && $mn > $mx) {
        out(['ok' => false, 'error' => 'sl_min_lebih_besar_dari_sl_max'], 400);
    }
    if (isset($in['mode'])) {
        $c['mode'] = $in['mode'] ? '1' : '0';
    }
    if (isset($in['tp_mode'])) {
        $v = (int) $in['tp_mode'];
        if ($v < 0 || $v > 3) {
            out(['ok' => false, 'error' => 'tp_mode'], 400);
        }
        $c['tp_mode'] = (string) $v;
    }
    foreach (['tp_usd', 'trail_start', 'trail_dist', 'be_at', 'be_lock'] as $key) {
        if (isset($in[$key])) {
            $v = (float) $in[$key];
            if ($v < 0 || $v > 1000000) {
                out(['ok' => false, 'error' => $key], 400);
            }
            $c[$key] = rtrim(rtrim(number_format($v, 2, '.', ''), '0'), '.');
        }
    }
    if (isset($c['be_at'], $c['be_lock']) && (float) $c['be_at'] > 0 && (float) $c['be_lock'] >= (float) $c['be_at']) {
        out(['ok' => false, 'error' => 'be_lock_harus_lebih_kecil_dari_be_at'], 400);
    }
    if (isset($in['flow_mode'])) {
        $v = (int) $in['flow_mode'];
        if ($v < 0 || $v > 2) {
            out(['ok' => false, 'error' => 'flow_mode'], 400);
        }
        $c['flow_mode'] = (string) $v;
    }
    // aturan dari halaman Analisa: blk_<MESIN> = jam WIB yang diblok, msp_<MESIN> = spread maksimal
    foreach ($in as $key => $val) {
        if (!preg_match('/^(blk|msp)_([A-Z0-9]+)$/', (string) $key, $m) || !in_array($m[2], $engines, true)) {
            continue;
        }
        if ($m[1] === 'blk') {
            $hrs = [];
            foreach (preg_split('/[,\s]+/', (string) $val, -1, PREG_SPLIT_NO_EMPTY) as $h) {
                if (!ctype_digit($h) || (int) $h > 23) {
                    out(['ok' => false, 'error' => $key], 400);
                }
                $hrs[(int) $h] = true;
            }
            ksort($hrs);
            $c[$key] = implode(',', array_keys($hrs));
        } else {
            $v = (float) $val;
            if ($v < 0 || $v > 100) {
                out(['ok' => false, 'error' => $key], 400);
            }
            $c[$key] = rtrim(rtrim(number_format($v, 2, '.', ''), '0'), '.');
        }
    }
    if (!empty($in['close_all'])) {
        $c['close_all'] = (string) time();     // nomor perintah baru; EA menjalankannya sekali
    }

    if (!$demo) {
        $txt = '';
        foreach ($c as $k => $v) {
            $txt .= $k . '=' . $v . "\r\n";
        }
        if (@file_put_contents($controlFile, $txt, LOCK_EX) === false) {
            out(['ok' => false, 'error' => 'write_failed'], 500);
        }
    }
    out(['ok' => true, 'demo' => $demo, 'control' => $c]);
}

// --- analisa: jalankan analysis/analyze.py dan baca hasilnya
$anaFile = $dir . DIRECTORY_SEPARATOR . 'MTRB_Pro_analysis.json';

function runAnalysis($cfg, $dir)
{
    $py     = isset($cfg['python']) && $cfg['python'] !== '' ? $cfg['python'] : 'python';
    $script = dirname(__DIR__) . DIRECTORY_SEPARATOR . 'analysis' . DIRECTORY_SEPARATOR . 'analyze.py';
    $cmd    = escapeshellarg($py) . ' -I ' . escapeshellarg($script) . ' --data ' . escapeshellarg($dir);
    if (DIRECTORY_SEPARATOR === '\\' && PHP_VERSION_ID < 80000) {
        $cmd = '"' . $cmd . '"';             // PHP 7 di Windows: cmd.exe membuang kutip terluar
    }
    $o  = [];
    $rc = 0;
    @exec($cmd . ' 2>&1', $o, $rc);
    return ['rc' => $rc, 'log' => implode("\n", array_slice($o, -6))];
}

if ($a === 'analysis' || $a === 'analyze') {
    if ($demo) {
        out(['ok' => false, 'error' => 'demo']);
    }
    $run = null;
    if ($a === 'analyze') {
        if ($_SERVER['REQUEST_METHOD'] !== 'POST') {
            out(['ok' => false, 'error' => 'method'], 405);
        }
        $run = runAnalysis($cfg, $dir);
    } else {
        // otomatis: analisa ulang kalau ada trade baru dan hasil terakhir lebih tua dari 30 menit
        $newest = 0;
        foreach (['MTRB_Pro_history.csv', 'MTRB_Pro_tradelog.csv'] as $f) {
            if (is_file($dir . DIRECTORY_SEPARATOR . $f)) {
                $newest = max($newest, filemtime($dir . DIRECTORY_SEPARATOR . $f));
            }
        }
        $at = is_file($anaFile) ? filemtime($anaFile) : 0;
        if ($newest > 0 && ($at === 0 || ($newest > $at && time() - $at > 1800))) {
            $run = runAnalysis($cfg, $dir);
        }
    }
    clearstatcache();
    if (!is_file($anaFile)) {
        out(['ok' => false, 'error' => $run ? 'run_failed' : 'no_data', 'log' => $run ? $run['log'] : '']);
    }
    $d = json_decode((string) file_get_contents($anaFile), true);
    if (!is_array($d)) {
        out(['ok' => false, 'error' => 'bad_analysis']);
    }
    out(['ok' => true, 'age' => time() - filemtime($anaFile), 'ran' => $run !== null, 'run_rc' => $run ? $run['rc'] : null,
         'run_log' => ($run && $run['rc'] !== 0) ? $run['log'] : '', 'data' => $d]);
}

// --- export riwayat trade ke CSV
if ($a === 'export') {
    $hist = $dir . DIRECTORY_SEPARATOR . 'MTRB_Pro_history.csv';
    $log  = $dir . DIRECTORY_SEPARATOR . 'MTRB_Pro_tradelog.csv';
    if ($demo) {
        out(['ok' => false, 'error' => 'demo']);
    }
    $readCsv = function ($f) {
        $rows = [];
        if (!is_file($f) || ($h = fopen($f, 'r')) === false) {
            return [[], []];
        }
        $head = fgetcsv($h, 0, ',', '"', '');
        while ($head && ($r = fgetcsv($h, 0, ',', '"', '')) !== false) {
            if (count($r) === count($head)) {
                $rows[] = array_combine($head, $r);
            }
        }
        fclose($h);
        return [$head ?: [], $rows];
    };
    list($hh, $hr) = $readCsv($hist);
    list($lh, $lr) = $readCsv($log);
    $withLog = !isset($_GET['basic']);
    $extra   = $withLog ? array_values(array_diff($lh, $hh)) : [];
    $byPos   = [];
    foreach ($lr as $r) {
        $byPos[$r['position']] = $r;
    }
    if (!$hr) {                           // belum ada file riwayat: pakai catatan analisa saja
        $hh = $lh ? array_slice($lh, 0, 11) : [];
        $hr = $lr;
    }
    if (!$hh) {
        out(['ok' => false, 'error' => 'no_data']);
    }
    $eng  = isset($_GET['engine']) ? (string) $_GET['engine'] : '';
    $from = isset($_GET['from']) && preg_match('/^\d{4}-\d{2}-\d{2}$/', $_GET['from']) ? str_replace('-', '.', $_GET['from']) : '';
    $to   = isset($_GET['to']) && preg_match('/^\d{4}-\d{2}-\d{2}$/', $_GET['to']) ? str_replace('-', '.', $_GET['to']) . ' 99' : '';
    $id   = isset($_GET['fmt']) && $_GET['fmt'] === 'id';
    $sep  = $id ? ';' : ',';
    $cols = array_merge($hh, $extra);
    $num  = '/^-?\d+(\.\d+)?$/';

    $outCsv = "\xEF\xBB\xBF" . implode($sep, $cols) . "\r\n";
    $n = 0;
    foreach ($hr as $r) {
        if ($eng !== '' && $r['engine'] !== $eng) {
            continue;
        }
        $ct = $r['close_time_wib'];
        if (($from !== '' && $ct < $from) || ($to !== '' && $ct > $to)) {
            continue;
        }
        $l    = isset($byPos[$r['position']]) ? $byPos[$r['position']] : [];
        $line = [];
        foreach ($cols as $c) {
            $v = isset($r[$c]) ? $r[$c] : (isset($l[$c]) ? $l[$c] : '');
            if (substr($c, -9) === '_time_wib') {
                $v = str_replace('.', '-', $v);
            } elseif ($id && preg_match($num, $v)) {
                $v = str_replace('.', ',', $v);
            }
            if (strpbrk($v, $sep . "\"\r\n") !== false) {
                $v = '"' . str_replace('"', '""', $v) . '"';
            }
            $line[] = $v;
        }
        $outCsv .= implode($sep, $line) . "\r\n";
        $n++;
    }
    header('Content-Type: text/csv; charset=utf-8');
    header('Content-Disposition: attachment; filename="mtrb_riwayat_' . date('Ymd_His') . '.csv"');
    header('X-Rows: ' . $n);
    echo $outCsv;
    exit;
}

out(['ok' => false, 'error' => 'unknown_action'], 400);
