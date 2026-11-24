# GET endpoints confirmed; detail response mapping remains provisional.
from decimal import Decimal
MODULES={'item':'Barang & Jasa','job-order':'Pekerjaan Pesanan','roll-over':'Penyelesaian Pesanan','receive-item':'Penerimaan Barang','delivery-order':'Pengiriman Pesanan','item-adjustment':'Penyesuaian Persediaan'}
class PreviewError(ValueError): pass

def fetch_records(get,module,start=None,end=None,page=1):
 from datetime import date
 if module not in MODULES or page<1: raise ValueError('module/page')
 params={'sp.page':page,'sp.pageSize':20}
 if start or end:
  if module=='item' or not start or not end: raise ValueError('date filter')
  a,b=date.fromisoformat(start),date.fromisoformat(end)
  if a>b: raise ValueError('date range')
  params.update({'filter.transDate.op':'BETWEEN','filter.transDate.val[0]':a.strftime('%d/%m/%Y'),'filter.transDate.val[1]':b.strftime('%d/%m/%Y')})
 result=get(module+'/list.do',params)
 if not isinstance(result.get('d'),list): raise PreviewError('Response list tidak berisi array d')
 records=[]; issues=[]
 for entry in result['d'][:20]:
  if not isinstance(entry,dict) or (entry.get('id') is None and not entry.get('number')):
   issues.append('List tidak memiliki ID transaksi'); continue
  try:
   record=get(module+'/detail.do',{'id':entry['id']} if entry.get('id') is not None else {'number':entry['number']}).get('d')
   if not isinstance(record,dict): raise PreviewError('Response detail bukan objek d')
   records.append(record)
  except Exception as e:
   issues.append('Detail ID '+str(entry.get('id') or entry.get('number'))+': '+(str(e) if isinstance(e,PreviewError) else type(e).__name__))
 return records,issues

def obj(v):
 return v if isinstance(v,dict) else {}

def name(v):
 if isinstance(v,dict): return name(v.get('name'))
 return v if isinstance(v,str) else ''

def scalar(v):
 return v if isinstance(v,(str,int)) and not isinstance(v,bool) else ''

def normalize(module,r,issues=None):
 if module=='item':
  return [(r['no'],'',r['no'],r['name'],'',name(r.get('unit1Name') or r.get('unit1')),'','',name(r.get('itemCategoryName') or r.get('itemCategory')))]
 if module=='roll-over' and r.get('rollOverType')=='ACCOUNT': return []
 if module=='roll-over' and r.get('rollOverType')!='ITEM': raise PreviewError('rollOverType belum dikenali')
 if not isinstance(r.get('detailItem'),list): raise PreviewError('detailItem bukan array')
 rows=[]
 for i,d in enumerate(r['detailItem'],1):
  try:
   if not isinstance(d,dict): raise PreviewError('detailItem bukan objek')
   item=obj(d.get('item'))
   code=scalar(d.get('itemNo')) or scalar(item.get('no'))
   if not code: raise PreviewError('kode barang tidak tersedia (itemNo/item.no)')
   try: qty=Decimal(str(d.get('quantity')))
   except Exception: raise PreviewError('quantity tidak valid') from None
   if not qty.is_finite(): raise PreviewError('quantity tidak finite')
   unit=name(d.get('itemUnitName') or d.get('itemUnit'))
   if not unit: raise PreviewError('satuan tidak tersedia (itemUnitName/itemUnit.name)')
   ref=scalar(r.get('jobOrderNumber')) or scalar(obj(r.get('jobOrder')).get('number'))
   if not ref and module=='job-order': ref=scalar(r.get('number'))
   rows.append((r['number'],r['transDate'],code,name(d.get('detailName')) or name(item),qty,unit,name(d.get('warehouseName') or d.get('warehouse')),ref,module))
  except (PreviewError,KeyError) as e:
   msg='Mapping transaksi '+str(r.get('id','?'))+' baris '+str(i)+': '+(str(e) if isinstance(e,PreviewError) else 'field header tidak tersedia')
   if issues is None: raise PreviewError(msg) from None
   issues.append(msg)
 return rows
