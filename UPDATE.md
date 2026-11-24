# v2.3 OAuth Scope Diagnostics
Backup PostgreSQL. Replace source files in GitHub, deploy Railway, keep SESSION_SECRET and all credentials unchanged. Set ACCURATE_SCOPE to item_view job_order_view roll_over_view receive_item_view delivery_order_view item_adjustment_view (single line). The app requests at least these six read scopes. Open dashboard, click Otorisasi ulang Accurate, grant access, choose the same database. Check Diagnostik izin OAuth for actual granted scopes. If all granted but HTTP 403 persists, verify Accurate user permissions and send the diagnostic message (no secrets). Preview remains read-only and is not posted to inventory reports. Detail uses id, or number if missing. No live API test performed.

## Hotfix v2.3.1
Dockerfile sekarang menyalin scope_diag.py ke /app. Ganti Dockerfile di GitHub dan pastikan scope_diag.py ada di root repository. Tidak perlu mengubah environment atau database. Uji import lokal menggunakan SQLite; bukan uji deployment Railway.
