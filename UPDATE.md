# v3.5 – Hotfix Sinkron Hasil Opname

- Dockerfile sekarang menyalin opname.py ke image Railway.
- Import modul opname berada dalam penanganan error.
- Tidak ada perubahan skema database atau scope OAuth.

## v3.4
- Perbaikan respons HTML halaman Dokumen Kepabeanan dan Riwayat Dokumen BC.
- Branding AOLINX Bea Cukai Reports. Tidak ada migrasi database atau perubahan OAuth.

# v3.2
Selisih = saldo akhir - hasil opname; kosong bila opname tidak tersedia. Admin bawaan tetap memakai ADMIN_PASSWORD. Kelola pengguna di /users (operator atau viewer). Hak akses diperiksa server; hanya admin dapat memilih database, menghubungkan atau memutuskan koneksi. Putuskan menghapus token lokal, mempertahankan database terpilih dan data laporan; tidak mencabut izin di Accurate. Sinkron ulang penerimaan/pengiriman untuk membaca charField1 (jenis BC) dan charField2 (nomor BC). Tanggal BC belum dipetakan. Uji API live masih diperlukan.

## v3.3
Menu Dokumen Kepabeanan untuk Admin dan EXIM. Filter tanggal transaksi, jenis, pencarian dan status; pilih satu atau banyak baris. Nomor BC teks, tanggal BC terpisah. Data BC tidak ditimpa sinkronisasi. Audit perubahan. Sinkron ulang untuk metadata nomor transaksi dan mitra. Satu dokumen per baris; pembagian qty belum didukung. Backup sebelum deploy.

# v3.6 – Automatic BC Mapping
- Isi deskripsi header Accurate: `BC 2.3 | 000125 | 23/11/2026`. Tanggal ISO juga diterima. Nomor disimpan sebagai teks.
- Sinkron ulang periode transaksi. Dokumen otomatis diterapkan pada setiap mutasi yang berhasil dipetakan; laporan 1–2 dan Excel memakai tabel BC yang sama. Laporan 3–7 tetap agregat.
- Data BC lama dianggap manual; koreksi manual tidak ditimpa. Jika deskripsi otomatis dihapus atau tidak valid, data otomatis lama dihapus dan perubahan dicatat di audit.
- Menu Dokumen Kepabeanan mendukung filter sumber dan mutasi produksi. Penyesuaian persediaan masih tidak diposting karena arah mutasi belum tervalidasi; parser tersedia untuk baris yang kelak berhasil dipetakan.
- Tabel bc_source dibuat otomatis tanpa menghapus data. Backup PostgreSQL sebelum deploy; pertahankan DATABASE_URL dan SESSION_SECRET.
- Uji lokal: compileall, import FastAPI dengan SQLite, unittest test_bc_mapping. Belum diuji terhadap API Accurate langsung atau PostgreSQL Railway.
