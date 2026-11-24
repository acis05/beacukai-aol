import os, secrets, io, time, html
from datetime import date
from decimal import Decimal
from urllib.parse import urlencode, urlparse
import httpx
from dotenv import load_dotenv
from fastapi import FastAPI, Request, UploadFile, File, HTTPException, Depends
from fastapi.responses import HTMLResponse, RedirectResponse, StreamingResponse
from fastapi.security import HTTPBasic, HTTPBasicCredentials
from starlette.middleware.sessions import SessionMiddleware
from sqlalchemy import create_engine, text
from openpyxl import load_workbook, Workbook
from cryptography.fernet import Fernet
load_dotenv()
app=FastAPI(); basic=HTTPBasic()
app.add_middleware(SessionMiddleware,secret_key=os.getenv('SESSION_SECRET') or secrets.token_hex(32),https_only=os.getenv('HTTPS_ONLY')=='true')
db_url=os.getenv('DATABASE_URL','sqlite:///inventory.db')
if db_url.startswith(('postgres://','postgresql://')):
 db_url='postgresql+psycopg://'+db_url.split('://',1)[1]
if os.getenv('RAILWAY_ENVIRONMENT'):
 for key in ('DATABASE_URL','ADMIN_PASSWORD','SESSION_SECRET','TOKEN_KEY'):
  if not os.getenv(key) or os.getenv(key).startswith('change-me'): raise RuntimeError('Missing secure variable: '+key)
 if not db_url.startswith('postgresql+psycopg://'): raise RuntimeError('PostgreSQL required on Railway')
 Fernet(os.environ['TOKEN_KEY'])
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
 d['expires_at']=time.time()+d['expires_in']; v=Fernet(os.environ['TOKEN_KEY']).encrypt(json.dumps(d).encode()).decode()
 with engine.begin() as c: c.execute(text("INSERT INTO settings VALUES ('token',:v) ON CONFLICT(k) DO UPDATE SET v=:v"),{'v':v})
def token_request(data):
 r=httpx.post('https://account.accurate.id/oauth/token',data=data,auth=(os.environ['ACCURATE_CLIENT_ID'],os.environ['ACCURATE_CLIENT_SECRET']),timeout=30); r.raise_for_status(); return r.json()
def token():
 import json
 with engine.connect() as c: v=c.execute(text("SELECT v FROM settings WHERE k='token'")).scalar()
 if not v: raise HTTPException(409,'Hubungkan Accurate dahulu')
 d=json.loads(Fernet(os.environ['TOKEN_KEY']).decrypt(v.encode()))
 if d['expires_at']<time.time()+60:
  new=token_request({'grant_type':'refresh_token','refresh_token':d['refresh_token']}); new.setdefault('refresh_token',d['refresh_token']); save_token(new); d=new
 return d['access_token']
@app.get('/oauth/start',dependencies=[Depends(auth)])
def start(r:Request):
 state=secrets.token_urlsafe(32); r.session['state']=state
 return RedirectResponse('https://account.accurate.id/oauth/authorize?'+urlencode({'client_id':os.environ['ACCURATE_CLIENT_ID'],'redirect_uri':os.environ['ACCURATE_REDIRECT_URI'],'response_type':'code','scope':os.getenv('ACCURATE_SCOPE','item_view'),'state':state}))
@app.get('/oauth/callback',dependencies=[Depends(auth)])
def callback(r:Request,code:str,state:str):
 if not secrets.compare_digest(r.session.pop('state',''),state): raise HTTPException(400,'State salah')
 save_token(token_request({'grant_type':'authorization_code','code':code,'redirect_uri':os.environ['ACCURATE_REDIRECT_URI']})); return RedirectResponse('/')
def api(url,headers,params=None):
 r=httpx.get(url,headers=headers,params=params,timeout=30); r.raise_for_status(); d=r.json()
 if not d.get('s'): raise HTTPException(502,'Accurate menolak permintaan')
 return d
@app.get('/databases',dependencies=[Depends(auth)])
def databases(): return api('https://account.accurate.id/api/db-list.do',{'Authorization':'Bearer '+token()})['d']
@app.post('/sync/items',dependencies=[Depends(auth)])
def sync(r:Request):
 guard(r); h={'Authorization':'Bearer '+token()}; d=api('https://account.accurate.id/api/open-db.do',h,{'id':os.environ['ACCURATE_DB_ID']}); host=d['host']; u=urlparse(host)
 if u.scheme!='https' or not u.hostname or not u.hostname.endswith('.accurate.id'): raise HTTPException(502,'Host tidak valid')
 h['X-Session-ID']=d['session']; page=1; rows=[]
 while True:
  d=api(host+'/accurate/api/item/list.do',h,{'fields':'id,no,name','sp.page':page}); rows.extend(d['d'])
  if page>=d['sp']['pageCount']: break
  page+=1
  if page>1000: raise HTTPException(502,'Batas halaman')
 with engine.begin() as c:
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
 return HTMLResponse('<meta charset=utf-8><a href="/">Kembali</a><h2>'+NAMES[n-1]+'</h2><p>Draft - belum tervalidasi</p><a href="?start='+str(start)+'&end='+str(end)+'&download=true">Excel</a><table border=1 cellpadding=8><tr>'+''.join('<th>'+esc(x)+'</th>' for x in h)+'</tr>'+''.join('<tr>'+''.join('<td>'+esc(x)+'</td>' for x in row)+'</tr>' for row in rows)+'</table>')
@app.get('/',response_class=HTMLResponse,dependencies=[Depends(auth)])
def home():
 return '<meta charset=utf-8><style>body{font:16px system-ui;max-width:1000px;margin:40px auto;padding:20px;background:#f4f7fb}section,form{background:white;padding:16px;margin:10px 0;border-radius:10px}button{padding:8px;background:#173b60;color:white;border:0;border-radius:5px}a{color:#173b60}</style><h1>IT Inventory Kawasan Berikat</h1><p>Versi uji • laporan belum tervalidasi</p><section><a href="/oauth/start">Hubungkan Accurate</a> | <a href="/databases">Daftar database</a><form method=post action="/sync/items"><button>Sinkron master barang</button></form></section><h2>Import data</h2>'+''.join(f'<form method=post enctype=multipart/form-data action="/import/{t}">{t} · <a href="/template/{t}">Template Excel</a> <input type=file name=file required accept=".xlsx"><button>Import</button></form>' for t in HEADERS)+'<h2>7 laporan</h2>'+''.join(f'<form action="/report/{i}"><b>{i}. {name}</b><br><input type=date name=start required> sampai <input type=date name=end required> <button>Lihat</button></form>' for i,name in enumerate(NAMES,1))

@app.get('/health')
def health():
 with engine.connect() as c: c.execute(text('SELECT 1'))
 return {'status':'ok'}
