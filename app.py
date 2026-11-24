import os, secrets, io, time, html, base64
from cryptography.hazmat.primitives import hashes
from cryptography.hazmat.primitives.kdf.hkdf import HKDF
from cryptography.fernet import InvalidToken
from datetime import date, datetime
from decimal import Decimal
from urllib.parse import urlencode, urlparse
import httpx
from scope_diag import scopes, requested, reason
from dotenv import load_dotenv
from fastapi import FastAPI, Request, UploadFile, File, HTTPException, Depends
from fastapi.responses import HTMLResponse, RedirectResponse, StreamingResponse
from fastapi.security import HTTPBasic, HTTPBasicCredentials
from starlette.middleware.sessions import SessionMiddleware
from sqlalchemy import create_engine, text
from openpyxl import load_workbook, Workbook
from cryptography.fernet import Fernet
load_dotenv()
session_secret=os.getenv('SESSION_SECRET','')
if len(session_secret)<32 or session_secret.startswith(('change-me','ISI_','GANTI_')):
 raise RuntimeError('SESSION_SECRET wajib acak, minimal 32 karakter; lihat RAILWAY.md')
key=HKDF(algorithm=hashes.SHA256(),length=32,salt=None,info=b'it-inventory/oauth-storage/v1').derive(session_secret.encode())
fernet=Fernet(base64.urlsafe_b64encode(key))
app=FastAPI(); basic=HTTPBasic()
app.add_middleware(SessionMiddleware,secret_key=session_secret,https_only=os.getenv('HTTPS_ONLY')=='true')
db_url=os.getenv('DATABASE_URL','sqlite:///inventory.db')
if db_url.startswith(('postgres://','postgresql://')):
 db_url='postgresql+psycopg://'+db_url.split('://',1)[1]
if os.getenv('RAILWAY_ENVIRONMENT'):
 for key in ('DATABASE_URL','ADMIN_PASSWORD','SESSION_SECRET'):
  if not os.getenv(key) or os.getenv(key).startswith('change-me'): raise RuntimeError('Missing secure variable: '+key)
 if not db_url.startswith('postgresql+psycopg://'): raise RuntimeError('PostgreSQL required on Railway')
engine=create_engine(db_url,pool_pre_ping=True)
with engine.begin() as c:
 for sql in ['CREATE TABLE IF NOT EXISTS items (code VARCHAR(100) PRIMARY KEY, name TEXT NOT NULL, category VARCHAR(30), unit VARCHAR(30))','CREATE TABLE IF NOT EXISTS movements (ref VARCHAR(200) PRIMARY KEY, day VARCHAR(10), code VARCHAR(100) REFERENCES items(code), qty NUMERIC(24,6), kind VARCHAR(20))','CREATE TABLE IF NOT EXISTS bc (ref VARCHAR(200) PRIMARY KEY, doc_type TEXT, doc_no TEXT, doc_date VARCHAR(10))','CREATE TABLE IF NOT EXISTS settings (k VARCHAR(50) PRIMARY KEY, v TEXT)','CREATE TABLE IF NOT EXISTS audit (event TEXT, stamp VARCHAR(40))']:
  c.execute(text(sql))
def auth(u:HTTPBasicCredentials=Depends(basic)):
 p=os.getenv('ADMIN_PASSWORD','');
 if not p or p=='change-me' or not secrets.compare_digest(u.username,'admin') or not secrets.compare_digest(u.password,p): raise HTTPException(401,'Login diperlukan',headers={'WWW-Authenticate':'Basic'})
def guard(r:Request):
 if r.headers.get('origin') != (os.getenv('PUBLIC_ORIGIN') or str(r.base_url)).rstrip('/'): raise HTTPException(403,'Origin tidak sesuai')
def audit(c,event): c.execute(text('INSERT INTO audit VALUES (:e,:t)'),{'e':event,'t':str(time.time())})
def save_token(d):
 import json
 d['expires_at']=time.time()+d['expires_in']; v=fernet.encrypt(json.dumps(d).encode()).decode()
 with engine.begin() as c: c.execute(text("INSERT INTO settings VALUES ('token',:v) ON CONFLICT(k) DO UPDATE SET v=:v"),{'v':v})
def token_request(data):
 r=httpx.post('https://account.accurate.id/oauth/token',data=data,auth=(os.environ['ACCURATE_CLIENT_ID'],os.environ['ACCURATE_CLIENT_SECRET']),timeout=30); r.raise_for_status(); return r.json()
def token_data():
 import json
 with engine.connect() as c: v=c.execute(text("SELECT v FROM settings WHERE k='token'")).scalar()
 if not v: raise HTTPException(409,'Hubungkan Accurate dahulu')
 try: d=json.loads(fernet.decrypt(v.encode()))
 except InvalidToken: raise HTTPException(409,'Token lama tidak dapat dibaca. Hubungkan Accurate kembali melalui halaman utama.')
 if d['expires_at']<time.time()+60:
  new=token_request({'grant_type':'refresh_token','refresh_token':d['refresh_token']}); new.setdefault('refresh_token',d['refresh_token']);
  if 'scope' in d: new.setdefault('scope',d['scope'])
  save_token(new); d=new
 return d
def token(): return token_data()['access_token']
def scope_panel():
 esc=lambda x:html.escape(str(x),quote=True)
 wanted=scopes(requested(os.getenv('ACCURATE_SCOPE','')))
 try: granted=scopes(token_data().get('scope'))
 except Exception: granted=None
 return '<section><h2>Diagnostik izin OAuth</h2><p>Scope diminta: '+esc(' '.join(sorted(wanted)))+'</p><p>Scope diberikan: '+esc(' '.join(sorted(granted)) if granted is not None else 'Belum diketahui; hubungkan ulang')+'</p><ul>'+''.join('<li>'+esc(k)+': '+('Diberikan' if granted is not None and k in granted else 'Belum diberikan' if granted is not None else 'Belum diketahui')+'</li>' for k in sorted(wanted))+'</ul><a class="btn" href="/oauth/start">Otorisasi ulang Accurate</a></section>'
@app.get('/oauth/start',dependencies=[Depends(auth)])
def start(r:Request):
 state=secrets.token_urlsafe(32); r.session['state']=state
 return RedirectResponse('https://account.accurate.id/oauth/authorize?'+urlencode({'client_id':os.environ['ACCURATE_CLIENT_ID'],'redirect_uri':os.environ['ACCURATE_REDIRECT_URI'],'response_type':'code','scope':requested(os.getenv('ACCURATE_SCOPE','')),'state':state}))
@app.get('/oauth/callback',dependencies=[Depends(auth)])
def callback(r:Request,code:str,state:str):
 if not secrets.compare_digest(r.session.pop('state',''),state): raise HTTPException(400,'State salah')
 save_token(token_request({'grant_type':'authorization_code','code':code,'redirect_uri':os.environ['ACCURATE_REDIRECT_URI']})); return RedirectResponse('/databases')
def api(url,headers,params=None):
 r=httpx.get(url,headers=headers,params=params,timeout=30); r.raise_for_status(); d=r.json()
 if not d.get('s'): raise HTTPException(502,'Accurate menolak permintaan')
 return d
def selected_db():
 with engine.connect() as c: return c.execute(text("SELECT v FROM settings WHERE k='db_id'")).scalar()
def available_dbs():
 return api('https://account.accurate.id/api/db-list.do',{'Authorization':'Bearer '+token()})['d']
@app.get('/databases',response_class=HTMLResponse,dependencies=[Depends(auth)])
def databases():
 current=selected_db(); esc=lambda x:html.escape(str(x),quote=True)
 options=''.join('<option value="'+esc(d['id'])+'"'+(' selected' if str(d['id'])==current else '')+'>'+esc(d.get('alias') or d.get('name') or d['id'])+'</option>' for d in available_dbs())
 return page('Pilih database Accurate','<section><p>Database dikunci setelah data diimpor atau disinkronkan. Gunakan instalasi terpisah untuk perusahaan lain.</p><form method="post" action="/databases/select"><select name="db_id" required>'+options+'</select><button>Simpan pilihan</button></form></section>')
@app.post('/databases/select',dependencies=[Depends(auth)])
async def select_database(r:Request):
 guard(r); form=await r.form(); db_id=str(form.get('db_id',''))
 if db_id not in {str(d['id']) for d in available_dbs()}: raise HTTPException(403,'Database tidak diizinkan')
 with engine.begin() as c:
  if engine.dialect.name=='postgresql': c.execute(text('LOCK TABLE settings, items, movements, bc IN SHARE ROW EXCLUSIVE MODE'))
  old=c.execute(text("SELECT v FROM settings WHERE k='db_id'")).scalar()
  if old!=db_id and any(c.execute(text('SELECT COUNT(*) FROM '+t)).scalar() for t in ('items','movements','bc')): raise HTTPException(409,'Data lokal sudah ada. Jangan mencampur perusahaan; gunakan database PostgreSQL baru atau migrasi terverifikasi.')
  c.execute(text("INSERT INTO settings VALUES ('db_id',:v) ON CONFLICT(k) DO UPDATE SET v=:v"),{'v':db_id}); audit(c,'select database '+db_id)
 return RedirectResponse('/',303)
@app.post('/sync/items',dependencies=[Depends(auth)])
def sync(r:Request):
 guard(r); db_id=selected_db()
 if not db_id: raise HTTPException(409,'Pilih database Accurate dahulu')
 h={'Authorization':'Bearer '+token()}; d=api('https://account.accurate.id/api/open-db.do',h,{'id':db_id}); host=d['host']; u=urlparse(host)
 if u.scheme!='https' or not u.hostname or not u.hostname.endswith('.accurate.id'): raise HTTPException(502,'Host tidak valid')
 h['X-Session-ID']=d['session']; page=1; rows=[]
 while True:
  d=api(host+'/accurate/api/item/list.do',h,{'fields':'id,no,name','sp.page':page}); rows.extend(d['d'])
  if page>=d['sp']['pageCount']: break
  page+=1
  if page>1000: raise HTTPException(502,'Batas halaman')
 with engine.begin() as c:
  if engine.dialect.name=='postgresql': c.execute(text('LOCK TABLE settings, items IN SHARE ROW EXCLUSIVE MODE'))
  if c.execute(text("SELECT v FROM settings WHERE k='db_id'")).scalar()!=db_id: raise HTTPException(409,'Pilihan database berubah; ulangi sinkronisasi')
  for x in rows: c.execute(text('INSERT INTO items(code,name) VALUES (:code,:name) ON CONFLICT(code) DO UPDATE SET name=:name'),{'code':x['no'],'name':x['name']})
  audit(c,'sync items '+str(len(rows)))
 return RedirectResponse('/',303)
CATS=['BB','BP','FG','WIP','ASET','SCRAP']; KINDS=['IN','OUT','PROD','TRANSFER','ADJ','OPEN']
HEADERS={'items':['code','name','category','unit'],'movements':['ref','day','code','qty','kind'],'bc':['ref','doc_type','doc_no','doc_date']}
@app.get('/template/{table}',dependencies=[Depends(auth)])
def template(table:str):
 if table not in HEADERS: raise HTTPException(404)
 return excel(HEADERS[table],[],table)
def excel(headers,rows,name):
 w=Workbook(); s=w.active; s.append(headers)
 for row in rows:
  s.append(list(row))
  for cell in s[s.max_row]:
   if isinstance(cell.value,str): cell.data_type='s'
 b=io.BytesIO(); w.save(b); b.seek(0); return StreamingResponse(b,media_type='application/vnd.openxmlformats-officedocument.spreadsheetml.sheet',headers={'Content-Disposition':f'attachment; filename={name}.xlsx'})
@app.post('/import/{table}',dependencies=[Depends(auth)])
def upload(r:Request,table:str,file:UploadFile=File(...)):
 guard(r)
 if not selected_db(): raise HTTPException(409,'Pilih database Accurate sebelum import')
 if table not in HEADERS: raise HTTPException(404)
 try:
  raw=file.file.read(5_000_001)
  if len(raw)>5_000_000: raise ValueError('File terlalu besar')
  w=load_workbook(io.BytesIO(raw),read_only=True,data_only=True); rows=iter(w.active.values); cols=HEADERS[table]
  if list(next(rows))!=cols: raise ValueError('Header tidak sesuai template')
  with engine.begin() as c:
   for i,row in enumerate(rows,2):
    if i>100002: raise ValueError('Terlalu banyak baris')
    if all(v is None for v in row): continue
    if len(row)!=len(cols) or any(v is None for v in row): raise ValueError(f'Baris {i} tidak lengkap')
    d=dict(zip(cols,[str(v).strip() for v in row]));
    if table=='items' and d['category'] not in CATS: raise ValueError('Kategori salah')
    if table=='movements':
     d['day']=date.fromisoformat(d['day'][:10]).isoformat(); q=Decimal(d['qty']);
     if not q.is_finite() or q==0 or d['kind'] not in KINDS or (d['kind']=='IN' and q<0) or (d['kind']=='OUT' and q>0): raise ValueError('Mutasi tidak valid')
     if not c.execute(text('SELECT code FROM items WHERE code=:code'),d).scalar(): raise ValueError('Kode barang tidak ditemukan')
     d['qty']=q if engine.dialect.name=='postgresql' else str(q)
    if table=='bc':
     d['doc_date']=date.fromisoformat(d['doc_date'][:10]).isoformat()
     if not c.execute(text('SELECT ref FROM movements WHERE ref=:ref'),d).scalar(): raise ValueError('Referensi mutasi tidak ditemukan')
    c.execute(text(f"INSERT INTO {table} ({','.join(cols)}) VALUES ({','.join(':'+k for k in cols)}) ON CONFLICT({cols[0]}) DO UPDATE SET "+','.join(k+'=:'+k for k in cols[1:])),d)
   audit(c,'import '+table)
 except Exception as e: raise HTTPException(400,'Import gagal; periksa format, referensi dan nilai data') from e
 return RedirectResponse('/',303)
NAMES=['Pemasukan Barang','Pengeluaran Barang','Mutasi Bahan Baku dan Penolong','Mutasi Barang Jadi','Posisi WIP','Mutasi Mesin dan Peralatan','Mutasi Scrap']
def report(n,start,end):
 if n not in range(1,8) or start>end: raise HTTPException(400,'Filter salah')
 with engine.connect() as c:
  p={'a':start.isoformat(),'b':end.isoformat()}
  if n<=2:
   p['kind']='IN' if n==1 else 'OUT'; sql='SELECT m.day,m.ref,m.code,i.name,i.unit,m.qty,b.doc_type,b.doc_no,b.doc_date FROM movements m JOIN items i ON i.code=m.code LEFT JOIN bc b ON b.ref=m.ref WHERE m.day BETWEEN :a AND :b AND m.kind=:kind ORDER BY m.day,m.ref'; headers=['Tanggal','Referensi','Kode','Barang','Satuan','Qty bertanda','Jenis BC','Nomor BC','Tanggal BC']
  else:
   p['cat']={3:'BB',4:'FG',5:'WIP',6:'ASET',7:'SCRAP'}[n]; sql="SELECT i.code,i.name,i.unit,COALESCE(SUM(CASE WHEN m.day<:a THEN m.qty ELSE 0 END),0),COALESCE(SUM(CASE WHEN m.day BETWEEN :a AND :b AND m.qty>0 AND m.kind<>'ADJ' THEN m.qty ELSE 0 END),0),COALESCE(SUM(CASE WHEN m.day BETWEEN :a AND :b AND m.qty<0 AND m.kind<>'ADJ' THEN -m.qty ELSE 0 END),0),COALESCE(SUM(CASE WHEN m.day BETWEEN :a AND :b AND m.kind='ADJ' THEN m.qty ELSE 0 END),0),COALESCE(SUM(CASE WHEN m.day<=:b THEN m.qty ELSE 0 END),0) FROM items i LEFT JOIN movements m ON m.code=i.code WHERE (i.category=:cat OR (:cat='BB' AND i.category='BP')) GROUP BY i.code,i.name,i.unit ORDER BY i.code"; headers=['Kode','Barang','Satuan','Awal','Masuk','Keluar','Penyesuaian','Akhir']
  return headers,c.execute(text(sql),p).fetchall()
@app.get('/report/{n}',dependencies=[Depends(auth)])
def view(n:int,start:date,end:date,download:bool=False):
 h,rows=report(n,start,end)
 if download:return excel(h,rows,'laporan_'+str(n))
 esc=lambda x:html.escape(str(x if x is not None else 'BELUM LENGKAP'))
 return HTMLResponse(page(NAMES[n-1],'<section><p>Draft - belum tervalidasi</p>'+('<p class="notice">Tidak ada baris sesuai periode/kategori. Import mutasi dan klasifikasi barang terlebih dahulu.</p>' if not rows else '')+'<a href="?start='+str(start)+'&end='+str(end)+'&download=true">Excel</a><table border=1 cellpadding=8><tr>'+''.join('<th>'+esc(x)+'</th>' for x in h)+'</tr>'+''.join('<tr>'+''.join('<td>'+esc(x)+'</td>' for x in row)+'</tr>' for row in rows)+'</table></section>'))
@app.get('/',response_class=HTMLResponse,dependencies=[Depends(auth)])
def home():
 with engine.connect() as c:
  counts=[c.execute(text('SELECT COUNT(*) FROM '+t)).scalar() for t in ('items','movements','bc')]
  connected=bool(c.execute(text("SELECT v FROM settings WHERE k='token'")).scalar())
 db=selected_db()
 esc=lambda x:html.escape(str(x))
 stats=''.join(f'<article class="metric"><small>{label}</small><strong>{value:,}</strong></article>' for label,value in zip(['Master barang','Baris mutasi lokal','Dokumen BC'],counts))
 body='<div class="metrics">'+stats+'</div><section id="integrasi"><h2>Integrasi Accurate Online</h2><p>Status OAuth: '+('Token tersimpan' if connected else 'Belum terhubung')+' · Database: '+esc(db or 'Belum dipilih')+'</p><div class="actions"><a class="btn" href="/oauth/start">Hubungkan Accurate</a><a class="btn secondary" href="/databases">Pilih database</a><form method="post" action="/sync/items"><button>Sinkron master barang</button></form></div><h3>Preview transaksi API (uji baca)</h3><p>Endpoint GET terkonfirmasi; mapping detail masih perlu validasi. Preview tidak mengubah transaksi atau laporan.</p><div class="actions">'+''.join(preview_form(k,v) for k,v in MODULES.items())+'</div></section>'
 body+=scope_panel()
 body+='<section id="import"><h2>Import data</h2>'+''.join(f'<form class="import" method="post" enctype="multipart/form-data" action="/import/{t}"><b>{label}</b><a href="/template/{t}">Template Excel</a><input type="file" name="file" required accept=".xlsx"><button>Import</button></form>' for t,label in zip(HEADERS,['Klasifikasi barang','Mutasi persediaan','Dokumen BC']))+'</section><section id="laporan"><h2>7 laporan Bea Cukai</h2><p class="notice">Draft — belum tervalidasi. Laporan menggunakan mutasi lokal. Unduh draft dari preview, validasi qty dan jenis mutasi, lalu import Excel.</p><div class="reports">'+''.join(f'<form class="report" action="/report/{i}"><small>LAPORAN {i:02}</small><h3>{name}</h3><label>Mulai<input type="date" name="start" required></label><label>Sampai<input type="date" name="end" required></label><button>Lihat laporan</button></form>' for i,name in enumerate(NAMES,1))+'</div></section>'
 return page('Dashboard',body)

# Professional interface and read-only transaction preview.
from ui import page
from accurate_read import MODULES, fetch_records, normalize

def preview_form(k,v):
 dates='' if k=='item' else '<label>Mulai<input type="date" name="start" required></label><label>Sampai<input type="date" name="end" required></label>'
 return f'<form method="get" action="/sync/preview/{k}" class="report"><b>{v}</b>{dates}<label>Halaman<input type="number" name="page_no" min="1" value="1" required></label><button class="secondary">Baca data</button></form>'

@app.get('/sync/preview/{module}', dependencies=[Depends(auth)])
def preview(r:Request,module:str,start:str=None,end:str=None,page_no:int=1,download:bool=False):
 import json, logging
 from accurate_read import PreviewError
 if module not in MODULES: raise HTTPException(404)
 esc=lambda v:html.escape(str(v),quote=True)
 stage='OAuth / database'
 def fail(message):
  return HTMLResponse(page(MODULES[module], '<section><h2>Pembacaan belum berhasil</h2><p class="notice">'+esc(message)+'</p><p>Scope yang diperlukan: <code>'+esc(module.replace('-','_')+'_view')+'</code></p><p>Periksa izin di Accurate Developer dan hubungkan ulang OAuth jika scope berubah.</p><a class="btn" href="/#integrasi">Kembali ke integrasi</a></section>'),status_code=502)
 try:
  db_id=selected_db()
  if not db_id: return fail('Pilih database dahulu.')
  td=token_data(); granted=scopes(td.get('scope')); need=module.replace('-','_')+'_view'
  if granted is not None and need not in granted: return fail('Scope belum diberikan oleh Accurate: '+need+'. Otorisasi ulang melalui dashboard.')
  h={'Authorization':'Bearer '+td['access_token']}
  d=api('https://account.accurate.id/api/open-db.do',h,{'id':db_id})
  host=d['host']; u=urlparse(host)
  if u.scheme!='https' or not u.hostname or not u.hostname.endswith('.accurate.id') or u.username or u.password or u.query or u.fragment: return fail('Host Accurate tidak valid.')
  h['X-Session-ID']=d['session']
  def get(path,params):
   nonlocal stage
   stage=path
   response=httpx.get(host.rstrip('/')+'/accurate/api/'+path,headers=h,params=params,timeout=30)
   if response.status_code!=200: raise PreviewError('HTTP '+str(response.status_code)+' pada '+path+' — '+reason(response))
   data=response.json()
   if not isinstance(data,dict): raise PreviewError('Response bukan objek JSON pada '+path)
   if data.get('s') is not True:
    # Do not expose arbitrary upstream messages or credentials.
    raise PreviewError('Accurate menolak '+path+' (s bukan true). Periksa scope, parameter dan izin database.')
   return data
  stage='list/detail'
  records,issues=fetch_records(get,module,start,end,page_no)
  if selected_db()!=db_id: return fail('Database berubah; ulangi pembacaan.')
 except PreviewError as e: return fail(str(e))
 except httpx.HTTPStatusError as e: return fail(stage+': HTTP '+str(e.response.status_code))
 except HTTPException as e: return fail(stage+': '+str(e.detail))
 except Exception as e:
  logging.getLogger('uvicorn.error').warning('Preview %s stage=%s type=%s',module,stage,type(e).__name__)
  return fail(stage+': '+type(e).__name__+'. Periksa log Railway.')
 rows=[]; candidates=[]
 for record in records:
  try:
   mapped=normalize(module,record,issues); rows.extend(mapped)
   if module!='item' and mapped:
    # Only export stable detail IDs; never guess direction or customs classification.
    for line in record.get('detailItem',[]):
     if not isinstance(line,dict) or line.get('id') is None or record.get('id') is None: continue
     single=dict(record,detailItem=[line]); one=normalize(module,single,[])
     if not one: continue
     v=one[0]
     try:
      day=str(v[1]); day=date.fromisoformat(day[:10]).isoformat() if '-' in day[:10] else datetime.strptime(day,'%d/%m/%Y').date().isoformat()
     except ValueError: continue
     ref=f"AOL:{db_id}:{module}:{record['id']}:{line['id']}"
     if len(ref)>200: continue
     candidates.append((ref,day,v[2],None,None,v[4],v[5],v[0]))
  except Exception as e: issues.append('Mapping transaksi '+str(record.get('id','?'))+': '+(str(e) if isinstance(e,PreviewError) else type(e).__name__))
 if download:
  if module=='item': raise HTTPException(400,'Gunakan sinkron master barang')
  w=Workbook(); sheet=w.active; sheet.title='Mutasi'; sheet.append(HEADERS['movements']); info=w.create_sheet('Referensi review'); info.append(['ref','day','code','qty API (belum bertanda)','satuan API','nomor transaksi']);
  for ref,day,code,qty,kind,raw,unit,num in candidates:
   sheet.append([ref,day,code,qty,kind]); info.append([ref,day,code,str(raw),unit,num])
  for ws in w:
   for rr in ws.iter_rows():
    for cell in rr:
     if isinstance(cell.value,str): cell.data_type='s'
  b=io.BytesIO(); w.save(b); b.seek(0); return StreamingResponse(b,media_type='application/vnd.openxmlformats-officedocument.spreadsheetml.sheet',headers={'Content-Disposition':'attachment; filename=review_mutasi.xlsx','Cache-Control':'no-store'})
 headers=['Nomor','Tanggal','Kode','Nama','Qty','Satuan','Gudang','Referensi pekerjaan','Tipe']
 body='<section><p class="notice">Preview saja; tidak mengubah Accurate atau buku mutasi. Detail berhasil: '+str(len(records))+'; kendala: '+str(len(issues))+'</p><a class="btn secondary" href="/#integrasi">Kembali</a>'
 if records and not rows: body+='<p class="notice">Detail tersedia tetapi tidak ada baris barang yang dapat dipetakan. Periksa struktur JSON di bawah; jangan anggap stok nol.</p>'
 if module=='item-adjustment': body+='<p>Qty API ditampilkan apa adanya, belum menentukan arah penyesuaian.</p>'
 if candidates:
  query=urlencode({'start':start or '', 'end':end or '', 'page_no':page_no,'download':'true'})
  body+='<p><a class="btn" href="?'+esc(query)+'">Unduh draft mutasi untuk review</a></p><p>Isi qty bertanda dalam satuan master dan kind pada Excel, lalu import Mutasi persediaan. Hanya baris dengan ID detail stabil disertakan: '+str(len(candidates))+' dari '+str(len(rows))+'. Jangan import ulang transaksi yang sudah dicatat dengan referensi lain.</p>'
 if issues: body+='<ul>'+''.join('<li>'+esc(x)+'</li>' for x in issues)+'</ul>'
 if not records and not issues: body+='<p>Tidak ada transaksi pada halaman/periode ini.</p>'
 if rows: body+='<div class="table-wrap"><table><thead><tr>'+''.join('<th>'+x+'</th>' for x in headers)+'</tr></thead><tbody>'+''.join('<tr>'+''.join('<td>'+esc(v)+'</td>' for v in row)+'</tr>' for row in rows)+'</tbody></table></div>'
 body+='<details><summary>Data detail API (internal admin)</summary><pre>'+esc(json.dumps(records,ensure_ascii=False,indent=2))+'</pre></details></section>'
 return HTMLResponse(page(MODULES[module],body),headers={'Cache-Control':'no-store'})

@app.get('/health')
def health():
 with engine.connect() as c: c.execute(text('SELECT 1'))
 return {'status':'ok'}
