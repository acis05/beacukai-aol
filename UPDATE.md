# Update v2.1
Upload seluruh isi ZIP ke repository lama. Pertahankan DATABASE_URL, SESSION_SECRET dan kredensial OAuth. Backup database dahulu.
Atur ACCURATE_SCOPE di Railway (pertahankan scope lama yang diperlukan): item_view job_order_view roll_over_view receive_item_view delivery_order_view item_adjustment_view. Hubungkan ulang Accurate dan setujui izin baru. Pastikan scope tersedia pada aplikasi developer.
Preview enam modul menggunakan GET, filter tanggal transaksi dan nomor halaman (20 record). Master item tanpa filter tanggal. Penyesuaian menampilkan JSON mentah. Parameter id pada detail dan bentuk response masih perlu uji live. Tidak ada penulisan transaksi Accurate. Preview tidak masuk laporan lokal. Laporan tetap draft.
