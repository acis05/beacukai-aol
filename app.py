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
from fastapi import Form, FastAPI, Request, UploadFile, File, HTTPException, Depends
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
 for sql in ['CREATE TABLE IF NOT EXISTS items (code VARCHAR(100) PRIMARY KEY, name TEXT NOT NULL, category VARCHAR(30), unit VARCHAR(30))','CREATE TABLE IF NOT EXISTS movements (ref VARCHAR(200) PRIMARY KEY, day VARCHAR(10), code VARCHAR(100) REFERENCES items(code), qty NUMERIC(24,6), kind VARCHAR(20))','CREATE TABLE IF NOT EXISTS bc (ref VARCHAR(200) PRIMARY KEY, doc_type TEXT, doc_no TEXT, doc_date VARCHAR(10))','CREATE TABLE IF NOT EXISTS settings (k VARCHAR(50) PRIMARY KEY, v TEXT)','CREATE TABLE IF NOT EXISTS accurate_categories (code VARCHAR(100) PRIMARY KEY, label TEXT)', 'CREATE TABLE IF NOT EXISTS audit (event TEXT, stamp VARCHAR(40))']:
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
 h['X-Session-ID']=d['session']
 from master_sync import master_rows
 def get(path,params): return api(host.rstrip('/')+'/accurate/api/'+path,h,params)
 try: rows=list(master_rows(get))
 except Exception as e: return HTMLResponse(page('Sinkron master gagal','<section><p class="notice">'+html.escape(str(e) if isinstance(e,ValueError) else type(e).__name__)+'</p><p>Periksa scope item_view dan item_category_view serta response detail.</p><a href="/">Kembali</a></section>'),status_code=502)
 with engine.begin() as c:
  if engine.dialect.name=='postgresql': c.execute(text('LOCK TABLE settings, items, movements IN SHARE ROW EXCLUSIVE MODE'))
  if c.execute(text("SELECT v FROM settings WHERE k='db_id'")).scalar()!=db_id: raise HTTPException(409,'Database berubah')
  for x in rows:
   old=c.execute(text('SELECT unit FROM items WHERE code=:code'),x).scalar()
   if old and x['unit'] and old.casefold()!=x['unit'].casefold() and c.execute(text('SELECT COUNT(*) FROM movements WHERE code=:code'),x).scalar(): raise HTTPException(409,'Satuan berubah untuk '+x['code']+'; rekonsiliasi dahulu')
   c.execute(text('INSERT INTO items(code,name,category,unit) VALUES (:code,:name,:category,:unit) ON CONFLICT(code) DO UPDATE SET name=:name,category=COALESCE(:category,items.category),unit=COALESCE(:unit,items.unit)'),x)
   c.execute(text('INSERT INTO accurate_categories(code,label) VALUES (:code,:label) ON CONFLICT(code) DO UPDATE SET label=:label'),x)
  audit(c,'sync items '+str(len(rows)))
 esc=lambda x:html.escape(str(x or 'Belum dikenali'))
 return HTMLResponse(page('Hasil sinkron master','<section><p>Master: '+str(len(rows))+'; satuan belum terbaca: '+str(sum(not x['unit'] for x in rows))+'; kategori BC belum dikenali otomatis: '+str(sum(not x['category'] for x in rows))+'</p><table><tr><th>Kode</th><th>Nama</th><th>Kategori Accurate</th><th>Kategori BC otomatis</th><th>Satuan</th></tr>'+''.join('<tr>'+''.join('<td>'+esc(x[k])+'</td>' for k in ('code','name','label','category','unit'))+'</tr>' for x in rows)+'</table><a href="/">Kembali</a></section>'))

CATS=['BB','BP','FG','WIP','ASET','SCRAP']; KINDS=['IN','OUT','PROD','TRANSFER','ADJ','OPEN']
HEADERS={'items':['code','name','category','unit'],'movements':['ref','day','code','qty','kind'],'bc':['ref','doc_type','doc_no','doc_date']}
@app.get('/template/{table}',dependencies=[Depends(auth)])
def template(table:str):
 raise HTTPException(410,'Import Excel dinonaktifkan pada mode uji tanpa dokumen BC')
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
 raise HTTPException(410,'Import Excel dinonaktifkan pada mode uji tanpa dokumen BC')
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
 except Exception as e: raise HTTPException(400,'Import gagal pada baris '+str(locals().get('i',1))+': '+(str(e) if isinstance(e,ValueError) else type(e).__name__)) from e
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
 with engine.connect() as c:
  diag=c.execute(text("SELECT kind,COUNT(*) FROM movements WHERE day BETWEEN :a AND :b GROUP BY kind ORDER BY kind"),{'a':start.isoformat(),'b':end.isoformat()}).fetchall()
  total=c.execute(text('SELECT COUNT(*) FROM movements')).scalar()
  unknown=c.execute(text("SELECT COUNT(*) FROM items WHERE category IS NULL OR category=''")).scalar()
 diagnostic='Total mutasi lokal: '+str(total)+'; periode: '+(', '.join(str(k)+': '+str(v) for k,v in diag) or '0 mutasi')+'; barang belum diklasifikasi: '+str(unknown)+'; baris laporan: '+str(len(rows))
 if download:return excel(h,rows,'laporan_'+str(n))
 esc=lambda x:html.escape(str(x if x is not None else ''))
 return HTMLResponse(page(NAMES[n-1],'<section><p>Draft uji tanpa dokumen BC — belum tervalidasi</p><p>'+esc(diagnostic)+'</p><a class="btn secondary" href="/#sinkron">Sinkronisasi transaksi</a> '+('<p class="notice">Tidak ada mutasi lokal sesuai periode/kategori. Periksa hasil sinkronisasi, tanggal transaksi, master dan satuan barang.</p>' if not rows else '')+'<a href="?start='+str(start)+'&end='+str(end)+'&download=true">Excel</a><table border=1 cellpadding=8><tr>'+''.join('<th>'+esc(x)+'</th>' for x in h)+'</tr>'+''.join('<tr>'+''.join('<td>'+esc(x)+'</td>' for x in row)+'</tr>' for row in rows)+'</table></section>'))
@app.get('/',response_class=HTMLResponse,dependencies=[Depends(auth)])
def home():
 with engine.connect() as c:
  counts=[c.execute(text('SELECT COUNT(*) FROM '+t)).scalar() for t in ('items','movements')]
  counts.append(c.execute(text("SELECT COUNT(*) FROM items WHERE category IS NULL OR category=''")).scalar())
  connected=bool(c.execute(text("SELECT v FROM settings WHERE k='token'")).scalar())
 db=selected_db()
 esc=lambda x:html.escape(str(x))
 stats=''.join(f'<article class="metric"><small>{label}</small><strong>{value:,}</strong></article>' for label,value in zip(['Master barang','Baris mutasi lokal','Barang belum diklasifikasi'],counts))
 body='<div class="metrics">'+stats+'</div><section id="integrasi"><h2>Integrasi Accurate Online</h2><p>Status OAuth: '+('Token tersimpan' if connected else 'Belum terhubung')+' · Database: '+esc(db or 'Belum dipilih')+'</p><div class="actions"><a class="btn" href="/oauth/start">Hubungkan Accurate</a><a class="btn secondary" href="/databases">Pilih database</a><form method="post" action="/sync/items"><button>Sinkron master barang</button></form></div><h3>Preview transaksi API (uji baca)</h3><p>Endpoint GET terkonfirmasi; mapping detail masih perlu validasi. Preview tidak mengubah transaksi atau laporan.</p><div class="actions">'+''.join(preview_form(k,v) for k,v in MODULES.items())+'</div></section>'
 body+='<section><a class="btn" href="/stock-history">Preview histori stok 7 hari</a></section>'+sync_panel()
 body+=scope_panel()
 body+='<section id="laporan"><h2>7 laporan Bea Cukai</h2><p class="notice">Draft — belum tervalidasi. Laporan menggunakan mutasi lokal. Gunakan sinkronisasi transaksi. Dokumen BC tidak wajib untuk uji laporan. Saldo awal belum tervalidasi.</p><div class="reports">'+''.join(f'<form class="report" action="/report/{i}"><small>LAPORAN {i:02}</small><h3>{name}</h3><label>Mulai<input type="date" name="start" required></label><label>Sampai<input type="date" name="end" required></label><button>Lihat laporan</button></form>' for i,name in enumerate(NAMES,1))+'</div></section>'
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

from sync_inventory import collect, MODULES as SYNC_MODULES

def sync_panel():
 return '<section id="sinkron"><h2>Sinkronisasi transaksi Accurate</h2><p class="notice">Mode draft: penerimaan/pengiriman diasumsikan mutasi eksternal; validasi kepabeanan tetap diperlukan. Penyesuaian belum diposting otomatis. Jangan sinkronkan periode yang sudah diimport manual.</p><form id="batch-sync" method="post" action="/sync/transactions"><label>Mulai<input type="date" name="start" required></label><label>Sampai<input type="date" name="end" required></label><label>Modul<select name="module"><option value="all">Semua transaksi</option>'+''.join('<option value="'+k+'">'+MODULES[k]+'</option>' for k in SYNC_MODULES)+'</select></label><label><input type="checkbox" name="confirm" value="yes" required> Saya sudah memeriksa klasifikasi, satuan, dan tidak ada duplikasi import manual.</label><button>Sinkronisasi transaksi</button></form><p id="batch-status" role="status"></p><div id="batch-results"></div></section>' + BATCH_SCRIPT

@app.post('/sync/transactions',dependencies=[Depends(auth)])
def sync_transactions(r:Request,start:date=Form(...),end:date=Form(...),module:str=Form(...),confirm:str=Form('')):
 guard(r)
 if start>end or confirm!='yes' or module not in (*SYNC_MODULES,'all'): return HTMLResponse(page('Periksa sinkronisasi','<section><p class="notice">Tanggal mulai harus sebelum atau sama dengan tanggal akhir, modul valid dan konfirmasi wajib dicentang.</p><a href="/#sinkron">Kembali</a></section>'),status_code=400)
 db_id=selected_db()
 if not db_id: raise HTTPException(409,'Pilih database dahulu')
 esc=lambda x:html.escape(str(x))
 results=[]
 try:
  h={'Authorization':'Bearer '+token()}; d=api('https://account.accurate.id/api/open-db.do',h,{'id':db_id}); host=d['host']; u=urlparse(host)
  if u.scheme!='https' or not u.hostname or not u.hostname.endswith('.accurate.id') or u.username or u.password or u.query or u.fragment: raise ValueError('Host invalid')
  h['X-Session-ID']=d['session']
  def get(path,params): return api(host.rstrip('/')+'/accurate/api/'+path,h,params)
  for k in SYNC_MODULES if module=='all' else (module,):
   try:
    with engine.connect() as c: masters={x[0]:(x[1],x[2]) for x in c.execute(text('SELECT code,unit,category FROM items'))}
    rows,issues,stats=collect(get,k,start,end,db_id,masters)
    summary=f"API: {stats['listed']} transaksi, {stats['details']} detail, {stats['outside']} di luar periode"
    if issues and not rows: results.append((MODULES[k],0,summary+'; Tidak disimpan: '+ '; '.join(issues[:30]))); continue
    with engine.begin() as c:
     if engine.dialect.name=='postgresql': c.execute(text('LOCK TABLE settings, items, movements, bc IN SHARE ROW EXCLUSIVE MODE'))
     if c.execute(text("SELECT v FROM settings WHERE k='db_id'")).scalar()!=db_id: raise ValueError('Database berubah')
     current={x[0]:(x[1],x[2]) for x in c.execute(text('SELECT code,unit,category FROM items'))}
     if current!=masters: raise ValueError('Master berubah')
     prefix=f'AOL:{db_id}:{k}:'
     existing=c.execute(text('SELECT ref FROM movements WHERE day BETWEEN :a AND :b'),{'a':start.isoformat(),'b':end.isoformat()}).scalars().all()
     if any(not x.startswith(f'AOL:{db_id}:') for x in existing): raise ValueError('Ada mutasi manual pada periode; rekonsiliasi dahulu')
     newrefs={x['ref'] for x in rows}
     if any(x.startswith(prefix) and x not in newrefs for x in existing): raise ValueError('Transaksi lama hilang/berubah tanggal; rekonsiliasi manual diperlukan')
     for row in rows:
      if engine.dialect.name=='postgresql': row['qty']=Decimal(row['qty'])
      c.execute(text('INSERT INTO movements(ref,day,code,qty,kind) VALUES (:ref,:day,:code,:qty,:kind) ON CONFLICT(ref) DO UPDATE SET day=:day,code=:code,qty=:qty,kind=:kind'),row)
     audit(c,'sync '+k+' '+str(len(rows)))
    results.append((MODULES[k],len(rows),'Disimpan/diperbarui; '+summary+('; KENDALA: '+'; '.join(issues[:30]) if issues else '') if rows else 'Tidak ada mutasi; '+summary))
   except Exception as e: results.append((MODULES[k],0,'Gagal: '+(str(e) if isinstance(e,ValueError) else type(e).__name__)))
 except Exception as e: results.append(('Koneksi',0,type(e).__name__))
 return HTMLResponse(page('Hasil sinkronisasi','<section><p class="notice">Draft. Periksa semua kendala sebelum menggunakan laporan.</p><table><tr><th>Modul</th><th>Baris</th><th>Status</th></tr>'+''.join('<tr>'+''.join('<td>'+esc(v)+'</td>' for v in x)+'</tr>' for x in results)+'</table><a class="btn" href="/#laporan">Buka laporan</a></section>'),headers={'Cache-Control':'no-store'})

BATCH_SCRIPT = """<script>
(()=>{const f=document.getElementById('batch-sync'); if(!f)return;
f.addEventListener('submit',async e=>{e.preventDefault();if(!f.reportValidity())return;
const data=new FormData(f), a=new Date(data.get('start')+'T00:00:00Z'), b=new Date(data.get('end')+'T00:00:00Z'), day=86400000;
const status=document.getElementById('batch-status'), out=document.getElementById('batch-results'), btn=f.querySelector('button');
if(a>b){status.textContent='Tanggal mulai melebihi tanggal akhir.';return;}
const mods=data.get('module')==='all'?Array.from(f.elements.module.options).map(x=>x.value).filter(x=>x!=='all'):[data.get('module')];
const total=Math.ceil((Math.round((b-a)/day)+1)/7)*mods.length;let done=0, failed=0;btn.disabled=true;out.replaceChildren();
const iso=x=>new Date(x).toISOString().slice(0,10);
try{for(let t=+a;t<=+b;t+=7*day){const end=Math.min(t+6*day,+b);for(const m of mods){
const label=iso(t)+' – '+iso(end)+' / '+m;status.textContent='Memproses '+(done+1)+'/'+total+' '+label+' — jangan tutup halaman.';
const payload=new FormData();for(const [k,v] of data)payload.set(k,v);payload.set('start',iso(t));payload.set('end',iso(end));payload.set('module',m);
const section=document.createElement('section'), heading=document.createElement('h3');heading.textContent=label;section.append(heading);out.append(section);
try{const res=await fetch(f.action,{method:'POST',body:payload,credentials:'same-origin'});const doc=new DOMParser().parseFromString(await res.text(),'text/html');const table=doc.querySelector('main table');if(!res.ok||!table)throw Error('HTTP '+res.status+' / hasil tidak tersedia');section.append(document.importNode(table,true));if(table.textContent.includes('KENDALA:')||!table.textContent.includes('Disimpan/diperbarui')&&!table.textContent.includes('Tidak ada mutasi;'))failed++;}catch(err){failed++;const p=document.createElement('p');p.textContent='Batch gagal atau status tidak diketahui: '+err.message;section.append(p);}
done++;}}status.textContent='Selesai '+done+'/'+total+' batch; '+failed+' bermasalah. Periksa hasil sebelum membuka laporan.';}finally{btn.disabled=false;}
});})();</script>"""

@app.get('/stock-history',dependencies=[Depends(auth)])
def stock_history(page_no:int=1):
 import json
 if page_no<1: raise HTTPException(400,'Halaman tidak valid')
 db_id=selected_db()
 if not db_id: raise HTTPException(409,'Pilih database dahulu')
 h={'Authorization':'Bearer '+token()}; d=api('https://account.accurate.id/api/open-db.do',h,{'id':db_id}); u=urlparse(d['host'])
 if u.scheme!='https' or not u.hostname or not u.hostname.endswith('.accurate.id') or u.username or u.password or u.query or u.fragment: raise HTTPException(502,'Host tidak valid')
 h['X-Session-ID']=d['session']
 result=api(d['host'].rstrip('/')+'/accurate/api/item/stock-mutation-history.do',h,{'sp.page':page_no,'sp.pageSize':20})
 return HTMLResponse(page('Histori stok Accurate','<section><p>Preview 7 hari terakhir; belum diposting agar tidak menggandakan mutasi.</p><pre>'+html.escape(json.dumps(result,ensure_ascii=False,indent=2))+'</pre><a href="/stock-history?page_no='+str(page_no+1)+'">Halaman berikutnya</a> · <a href="/">Kembali</a></section>'),headers={'Cache-Control':'no-store'})
