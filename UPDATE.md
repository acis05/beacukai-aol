# v2.7 Accurate First
Backup PostgreSQL, replace all repository files, redeploy. Keep SESSION_SECRET and DATABASE_URL. Enable item_category_view and stock_mutation_history_view, reconnect OAuth and select same database. Sync master then transactions. Excel import only BC; old data retained. Master mapping uses provisional response fields unit1/unit1Name and itemCategory/itemCategoryName/itemCategoryId; unknown categories displayed, existing classifications retained. Stock history is read-only preview, not automatic posting. Adjustment direction, opening balances, WIP and customs compliance remain unvalidated. Partial valid transaction batches can be saved; review all warnings. No live Accurate test.

## v2.8
Mode uji tanpa impor BC; endpoint impor dinonaktifkan, data lama dipertahankan. Laporan sudah memakai LEFT JOIN BC. Diagnostik jumlah mutasi dan kategori ditambahkan. Sinkronisasi tetap diperlukan.
