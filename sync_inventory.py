from datetime import date, datetime
from decimal import Decimal
from accurate_read import normalize, PreviewError, obj, name
def normalize_base_unit(line):
 return name(obj(line.get("item")).get("unit1"))
MODULES=('receive-item','delivery-order','job-order','roll-over','item-adjustment')
def day_of(v):
 try: return date.fromisoformat(str(v)[:10])
 except ValueError: return datetime.strptime(str(v),'%d/%m/%Y').date()
def collect(get,module,start,end,db_id,masters,unfiltered=False):
 rows=[]; issues=[]; seen=set(); stats={"listed":0,"outside":0,"details":0,"mode":"tanpa filter API" if unfiltered else "filter API"}
 p=1
 while True:
  params={'sp.page':p,'sp.pageSize':20}
  if not unfiltered:
   if start==end: params.update({'filter.transDate.op':'EQUAL','filter.transDate.val':start.strftime('%d/%m/%Y')})
   else: params.update({'filter.transDate.op':'BETWEEN','filter.transDate.val[0]':start.strftime('%d/%m/%Y'),'filter.transDate.val[1]':end.strftime('%d/%m/%Y')})
  data=get(module+'/list.do',params)
  if p==1 and not unfiltered and data.get('d')==[]:
   unfiltered=True; stats['mode']='fallback tanpa filter API'; continue
  entries=data['d']; count=int(data['sp']['pageCount'])
  if not isinstance(entries,list) or (not entries and p<count): raise PreviewError('Pagination tidak valid')
  for e in entries:
   stats['listed']+=1
   rid=e['id'];
   if rid in seen: raise PreviewError('ID berulang pada pagination')
   seen.add(rid)
   r=get(module+'/detail.do',{'id':rid})['d']
   stats['details']+=1
   if str(r.get('id'))!=str(rid): raise PreviewError('ID detail berbeda')
   if r.get('approvalStatus') not in (None,'APPROVED'): issues.append(f'{rid}: status belum disetujui'); continue
   if module=='roll-over' and r.get('rollOverType')=='ACCOUNT': continue
   try:
    day=day_of(r['transDate'])
    if not start<=day<=end:
     stats['outside']+=1; continue
    if not isinstance(r.get('detailItem'),list) or not r['detailItem']: raise ValueError('detailItem kosong/tidak dikenali')
    batch=[]; refs=set()
    for line in r['detailItem']:
     v=normalize(module,dict(r,detailItem=[line]))[0]; code=v[2]; q=v[4]; unit=v[5]
     if code not in masters: raise ValueError('Kode belum ada di master: '+str(code))
     master_unit, category=masters[code]
     if not master_unit: raise ValueError('Satuan master kosong: '+str(code))
     if module=='receive-item':
      base_unit=normalize_base_unit(line)
      if base_unit and master_unit.strip().casefold()==base_unit.strip().casefold():
       q=Decimal(str(line['quantityDefault'])) if line.get('quantityDefault') is not None else q*Decimal(str(line.get('unitRatio',1)))
      elif master_unit.strip().casefold()!=unit.strip().casefold(): raise ValueError('Satuan master berbeda: '+str(code)+' / '+unit+' / '+master_unit)
     elif master_unit.strip().casefold()!=unit.strip().casefold(): raise ValueError('Satuan belum sesuai: '+str(code))
     if not q.is_finite() or q<=0 or q>=Decimal('1000000000000000000') or q!=q.quantize(Decimal('0.000001')): raise ValueError('Qty tidak valid')
     if module=='item-adjustment': raise ValueError('Arah penyesuaian perlu validasi JSON asli')
     kind,sign={'receive-item':('IN',1),'delivery-order':('OUT',-1),'job-order':('PROD',-1),'roll-over':('PROD',1)}[module]
     ref=f"AOL:{db_id}:{module}:{rid}:{line['id']}"
     if line['id'] is None or len(ref)>200 or ref in refs: raise ValueError('ID detail tidak valid')
     refs.add(ref)
     value=None
     if module in ('receive-item','delivery-order') and line.get('itemCost') is not None:
      try:
       cost=Decimal(str(line['itemCost']))
       if cost.is_finite() and cost>=0: value=str(q*cost)
      except Exception: pass
     batch.append(dict(number=str(r.get("number") or rid),party=name(r.get("vendor") or r.get("customer") or r.get("vendorName") or r.get("customerName")),ref=ref,day=day.isoformat(),code=code,qty=str(q*sign),kind=kind,value=value,description=r.get("description"),detailNotes=line.get("detailNotes")))
    rows.extend(batch)
   except Exception as exc: issues.append(f'{rid}: '+(str(exc) if isinstance(exc,(ValueError,PreviewError)) else type(exc).__name__))
  if p>=count: return rows,issues,stats
  p+=1
