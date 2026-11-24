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

def name(v):
 return v.get('name','') if isinstance(v,dict) else (v or '')
def normalize(module,r):
 if module=='item':
  return [(r['no'],'',r['no'],r['name'],'',name(r.get('unit1Name') or r.get('unit1')),'','',name(r.get('itemCategoryName') or r.get('itemCategory')))]
 if module=='roll-over' and r.get('rollOverType')=='ACCOUNT': return []
 if module=='roll-over' and r.get('rollOverType')!='ITEM': raise ValueError('rollOverType')
 if not isinstance(r.get('detailItem'),list): raise ValueError('detailItem')
 rows=[]
 for d in r['detailItem']:
  item=d.get('item') or {}; code=d.get('itemNo') or item.get('no'); qty=Decimal(str(d['quantity']))
  unit=name(d.get('itemUnitName') or d.get('itemUnit'))
  if not code or not unit or not qty.is_finite(): raise ValueError('detail fields')
  rows.append((r['number'],r['transDate'],code,d.get('detailName') or item.get('name',''),qty,unit,name(d.get('warehouseName') or d.get('warehouse')),r.get('jobOrderNumber') or (r.get('jobOrder') or {}).get('number',''),module))
 return rows
