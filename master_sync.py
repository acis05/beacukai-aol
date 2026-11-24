from accurate_read import name, obj, PreviewError
import re
ALIASES={'bb':'BB','bahan baku':'BB','raw material':'BB','bp':'BP','bahan penolong':'BP','fg':'FG','barang jadi':'FG','finished goods':'FG','wip':'WIP','barang dalam proses':'WIP','aset':'ASET','mesin dan peralatan':'ASET','scrap':'SCRAP','barang sisa produksi':'SCRAP'}
def category_code(label): return ALIASES.get(' '.join(label.casefold().split()))
def pages(get,path,params=None):
 seen=set(); p=1
 while True:
  result=get(path,dict(params or {}, **{'sp.page':p,'sp.pageSize':20}))
  entries=result['d']; count=int(result['sp']['pageCount'])
  if not isinstance(entries,list) or (not entries and p<count): raise PreviewError('Pagination tidak valid')
  for entry in entries:
   rid=str(entry['id'])
   if rid in seen: raise PreviewError('ID berulang')
   seen.add(rid); yield entry
  if p>=count: break
  p+=1

def master_rows(get):
 categories={str(x['id']):name(x) for x in pages(get,'item-category/list.do')}
 for entry in pages(get,'item/list.do',{'fields':'id,no,name'}):
  r=get('item/detail.do',{'id':entry['id']})['d']
  if not isinstance(r,dict) or str(r.get('id'))!=str(entry['id']): raise PreviewError('Detail master tidak valid')
  label=name(r.get('itemCategoryName') or r.get('itemCategory')) or categories.get(str(r.get('itemCategoryId') or obj(r.get('itemCategory')).get('id')),'')
  unit=name(r.get('unit1Name') or r.get('unit1'))
  yield dict(code=str(r['no']),name=r['name'],unit=unit or None,category=category_code(label),label=label)
