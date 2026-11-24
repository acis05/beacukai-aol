# v2.6
- Penerimaan memakai quantity/quantityDefault sesuai satuan master, bukan availableQuantity.
- Pemasukan tidak mensyaratkan kategori barang, tetapi kode dan satuan master tetap wajib.
- Hasil sinkron menampilkan jumlah transaksi API, detail dan transaksi di luar periode; batch kosong tidak disebut berhasil menyimpan.
- Uji lokal menggunakan dua detail penerimaan yang diberikan pengguna: empat baris mutasi. API list disimulasikan; belum diuji di Railway.
- Pertahankan PostgreSQL, SESSION_SECRET dan konfigurasi OAuth. Backup sebelum deploy. Upload seluruh isi ZIP ke GitHub.
- Sinkron Penerimaan Barang 01/11/2026–24/11/2026, kemudian buka laporan Pemasukan pada periode yang sama. Pastikan satuan master PCS, KG, Ltr sesuai kode.
- Modul lain tetap draft; arah penyesuaian belum tervalidasi. Dokumen BC dan saldo awal tetap perlu dilengkapi.
