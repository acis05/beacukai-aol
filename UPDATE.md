# v3.2
Selisih = saldo akhir - hasil opname; kosong bila opname tidak tersedia. Admin bawaan tetap memakai ADMIN_PASSWORD. Kelola pengguna di /users (operator atau viewer). Hak akses diperiksa server; hanya admin dapat memilih database, menghubungkan atau memutuskan koneksi. Putuskan menghapus token lokal, mempertahankan database terpilih dan data laporan; tidak mencabut izin di Accurate. Sinkron ulang penerimaan/pengiriman untuk membaca charField1 (jenis BC) dan charField2 (nomor BC). Tanggal BC belum dipetakan. Uji API live masih diperlukan.

## v3.3
Menu Dokumen Kepabeanan untuk Admin dan EXIM. Filter tanggal transaksi, jenis, pencarian dan status; pilih satu atau banyak baris. Nomor BC teks, tanggal BC terpisah. Data BC tidak ditimpa sinkronisasi. Audit perubahan. Sinkron ulang untuk metadata nomor transaksi dan mitra. Satu dokumen per baris; pembagian qty belum didukung. Backup sebelum deploy.
