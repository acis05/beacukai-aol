from decimal import Decimal
from master_sync import pages
from sync_inventory import day_of

def collect_opname(get,start,end,masters):
    rows=[]
    for entry in pages(get,'stock-opname-result/list.do'):
        r=get('stock-opname-result/detail.do',{'id':entry['id']})['d']
        if str(r.get('id'))!=str(entry['id']): raise ValueError('ID opname berbeda')
        day=day_of(r['transDate'])
        if not start<=day<=end: continue
        if r.get('approvalStatus') not in (None,'APPROVED'): continue
        if not isinstance(r.get('detailItem'),list): raise ValueError('detailItem opname tidak tersedia')
        for line in r['detailItem']:
            code=str(line.get('itemNo') or (line.get('item') or {}).get('no') or '')
            if code not in masters: raise ValueError('Kode opname belum ada di master: '+code)
            q=Decimal(str(line['quantity']))
            if not q.is_finite() or q<0: raise ValueError('Qty opname tidak valid')
            rows.append(dict(ref=str(r['id'])+':'+str(line['id']),day=day.isoformat(),code=code,qty=str(q),doc=str(r['id'])))
    if len({x['ref'] for x in rows})!=len(rows): raise ValueError('ID detail opname ganda')
    return rows
