import re
from datetime import datetime
import json

def parse_bc(description):
    if not isinstance(description,str) or not description.strip(): return None, 'empty'
    parts=[p.strip() for p in description.split('|')]
    if len(parts)!=3 or not re.fullmatch(r'BC\s*\d+(?:\.\d+)?',parts[0],re.I) or not parts[1] or len(parts[1])>120 or '\n' in parts[1]: return None,'invalid'
    for fmt in ('%d/%m/%Y','%Y-%m-%d'):
        try: day=datetime.strptime(parts[2],fmt).date().isoformat(); break
        except ValueError: continue
    else: return None,'invalid'
    return ('BC '+re.sub(r'^BC\s*','',parts[0],flags=re.I),parts[1],day),'accurate'

def apply_bc(c,row,text):
    ref=row['ref']; data,status=parse_bc(row.get('description'))
    old=c.execute(text('SELECT doc_type,doc_no,doc_date FROM bc WHERE ref=:r'),{'r':ref}).fetchone()
    source=c.execute(text('SELECT source FROM bc_source WHERE ref=:r'),{'r':ref}).scalar()
    if source=='manual' or (old and source is None): return 'manual'
    if data:
        c.execute(text('INSERT INTO bc(ref,doc_type,doc_no,doc_date) VALUES (:r,:t,:n,:d) ON CONFLICT(ref) DO UPDATE SET doc_type=:t,doc_no=:n,doc_date=:d'),dict(zip(('r','t','n','d'),(ref,*data))))
    elif old:
        c.execute(text('DELETE FROM bc WHERE ref=:r'),{'r':ref})
    c.execute(text('INSERT INTO bc_source(ref,source) VALUES (:r,:s) ON CONFLICT(ref) DO UPDATE SET source=:s'),{'r':ref,'s':status})
    if (tuple(old) if old else None)!=data:
        c.execute(text('INSERT INTO customs_audit VALUES (:s,:u,:r,:o,:n)'),{'s':datetime.utcnow().isoformat()+'Z','u':'Accurate','r':ref,'o':json.dumps(list(old) if old else None),'n':json.dumps(data)})
    return status
