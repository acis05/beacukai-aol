import unittest
from sqlalchemy import create_engine,text
from bc_mapping import parse_bc,apply_bc
class TestBC(unittest.TestCase):
 def test_parser(self):
  self.assertEqual(parse_bc('BC 2.3 | 000125 | 23/11/2026'),(('BC 2.3','000125','2026-11-23'),'accurate'))
  self.assertEqual(parse_bc('BC 2.3 | 1 | 31/02/2026')[1],'invalid')
  self.assertEqual(parse_bc(None)[1],'empty')
 def test_sync(self):
  with create_engine('sqlite://').begin() as c:
   for sql in ['CREATE TABLE bc(ref TEXT PRIMARY KEY,doc_type TEXT,doc_no TEXT,doc_date TEXT)','CREATE TABLE bc_source(ref TEXT PRIMARY KEY,source TEXT)','CREATE TABLE customs_audit(stamp TEXT,username TEXT,ref TEXT,old_data TEXT,new_data TEXT)']: c.execute(text(sql))
   row={'ref':'a','description':'BC 2.3 | 000125 | 23/11/2026'}
   self.assertEqual(apply_bc(c,row,text),'accurate'); apply_bc(c,row,text)
   self.assertEqual(c.execute(text('SELECT COUNT(*) FROM customs_audit')).scalar(),1)
   row['description']='BC 4.0 | 000126 | 24/11/2026'; apply_bc(c,row,text)
   self.assertEqual(c.execute(text('SELECT doc_no FROM bc')).scalar(),'000126')
   c.execute(text("UPDATE bc_source SET source='manual'")); row['description']=None
   self.assertEqual(apply_bc(c,row,text),'manual'); self.assertEqual(c.execute(text('SELECT doc_no FROM bc')).scalar(),'000126')
   c.execute(text("UPDATE bc_source SET source='accurate'")); apply_bc(c,row,text)
   self.assertEqual(c.execute(text('SELECT COUNT(*) FROM bc')).scalar(),0)
if __name__=='__main__': unittest.main()
