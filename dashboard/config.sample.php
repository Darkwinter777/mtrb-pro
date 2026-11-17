<?php
// Pengaturan dashboard MTRB Pro.
return [
    // Folder "Common\Files" milik MetaTrader 5, tempat EA menulis status dan membaca perintah.
    // Di VPS Linux (Wine) biasanya: /home/<user>/.wine/drive_c/users/<user>/AppData/Roaming/MetaQuotes/Terminal/Common/Files
    'data_dir' => 'C:\Users\NAMA_USER\AppData\Roaming\MetaQuotes\Terminal\Common\Files',

    // PIN untuk akses dari perangkat lain (HP di jaringan yang sama, atau internet).
    // Kosong = dashboard hanya bisa dibuka dari komputer ini sendiri (localhost).
    'pin' => '',

    // Python untuk halaman Analisa (butuh pandas dan scikit-learn). Isi path lengkap kalau "python" tidak dikenali server web.
    'python' => 'python',
];
