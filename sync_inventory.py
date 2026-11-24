from datetime import date, datetime
from decimal import Decimal
from accurate_read import normalize, PreviewError
MODULES=('receive-item','delivery-order','job-order','roll-over','item-adjustment')
def day_of(v):
 try: return date.fromisoformat(str(v)[:10])
 except ValueError: return datetime.strptime(str(v),'%d/%m/%Y').date()
def collect(get,module,start,end,db_id,masters):
 rows=[]; issues=[]; seen=set()
 p=1
 while True:
  data=get(module+'/list.do',{'sp.page':p,'sp.pageSize':20,'filter.transDate.op':'BETWEEN','filter.transDate.val[0]':start.strftime('%d/%m/%Y'),'filter.transDate.val[1]':end.strftime('%d/%m/%Y')})
  entries=data['d']; count=int(data['sp']['pageCount'])
  if not isinstance(entries,list) or (not entries and p<count): raise PreviewError('Pagination tidak valid')
  for e in entries:
   rid=e['id'];
   if rid in seen: raise PreviewError('ID berulang pada pagination')
   seen.add(rid)
   r=get(module+'/detail.do',{'id':rid})['d']
   if str(r.get('id'))!=str(rid): raise PreviewError('ID detail berbeda')
   if r.get('approvalStatus') not in (None,'APPROVED'): issues.append(f'{rid}: status belum disetujui'); continue
   if module=='roll-over' and r.get('rollOverType')=='ACCOUNT': continue
   try:
    day=day_of(r['transDate']); assert start<=day<=end
    if not isinstance(r.get('detailItem'),list) or not r['detailItem']: raise ValueError('detailItem kosong/tidak dikenali')
    batch=[]; refs=set()
    for line in r['detailItem']:
     v=normalize(module,dict(r,detailItem=[line]))[0]; code=v[2]; q=v[4]; unit=v[5]
     if code not in masters or masters[code][0]!=unit or not masters[code][1]: raise ValueError('Master, kategori atau satuan belum sesuai: '+str(code))
     if q<=0 or q>=Decimal('1000000000000000000') or q!=q.quantize(Decimal('0.000001')): raise ValueError('Qty tidak valid')
     if module=='item-adjustment': raise ValueError('Arah penyesuaian perlu validasi JSON asli')
     kind,sign={'receive-item':('IN',1),'delivery-order':('OUT',-1),'job-order':('PROD',-1),'roll-over':('PROD',1)}[module]
     ref=f"AOL:{db_id}:{module}:{rid}:{line['id']}"
     if line['id'] is None or len(ref)>200 or ref in refs: raise ValueError('ID detail tidak valid')
     refs.add(ref); batch.append(dict(ref=ref,day=day.isoformat(),code=code,qty=str(q*sign),kind=kind))
    rows.extend(batch)
   except Exception as exc: issues.append(f'{rid}: '+(str(exc) if isinstance(exc,(ValueError,PreviewError)) else type(exc).__name__))
  if p>=count: return rows,issues
  p+=1
