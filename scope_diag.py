import re
REQUIRED='item_view item_category_view stock_mutation_history_view job_order_view roll_over_view receive_item_view delivery_order_view item_adjustment_view stock_opname_result_view'
def scopes(value):
    if not isinstance(value,str): return None
    return {x for x in re.split(r'[\s,]+',value) if re.fullmatch(r'[a-zA-Z0-9_]+',x)}
def requested(value):
    return ' '.join(sorted((scopes(value) or set()) | set(REQUIRED.split())))
def reason(response):
    raw=response.headers.get('WWW-Authenticate','')+' '+response.text[:8192]
    for code in ('insufficient_scope','invalid_token'):
        if re.search(r'\b'+code+r'\b',raw,re.I): return code
    return 'izin ditolak; periksa hak akses pengguna/database' if response.status_code==403 else 'permintaan gagal'
