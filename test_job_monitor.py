import unittest,time
from job_monitor import classify,fingerprint
class Tests(unittest.TestCase):
    def setUp(self):
        self.now=time.time(); self.v={'id':1,'profession':'Главный геодезист','firm_name':'Test','town':{'title':'Москва'},'address':'Москва','type_of_work':{'title':'Полный рабочий день'},'date_published':int(self.now),'link':'https://www.superjob.ru/vakansii/test-1.html'}
    def test_valid(self): self.assertEqual(classify(self.v,self.now)[0],1)
    def test_rotation(self): self.v['work']='Вахта'; self.assertIsNone(classify(self.v,self.now)[0])
    def test_unknown_schedule(self): self.v['type_of_work']=''; self.assertIsNone(classify(self.v,self.now)[0])
    def test_unknown_site(self): self.v['address']=''; self.assertIsNone(classify(self.v,self.now)[0])
    def test_old(self): self.v['date_published']-=800000; self.assertIsNone(classify(self.v,self.now)[0])
    def test_archive(self): self.v['is_archive']=True; self.assertIsNone(classify(self.v,self.now)[0])
    def test_duplicate(self): a=fingerprint(self.v); self.v['id']=2; self.assertEqual(a,fingerprint(self.v))
if __name__=='__main__': unittest.main()
