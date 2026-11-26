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
    def test_no_rotation(self): self.v['compensation']='Без вахты, 5/2'; self.assertEqual(classify(self.v,self.now)[0],1)
    def test_mixed_rotation(self): self.v['compensation']='Без вахты в Москве, возможна вахта'; self.assertIsNone(classify(self.v,self.now)[0])
    def test_suburb(self): self.v['town']={'title':'Химки'}; self.v['address']='Химки'; self.assertEqual(classify(self.v,self.now)[0],1)
    def test_outside(self): self.v['work']='Объект в Тульской области'; self.assertIsNone(classify(self.v,self.now)[0])
    def test_town_only(self): self.v['address']=''; self.assertIsNone(classify(self.v,self.now)[0])
    def test_bad_town(self): self.v['town']={'title':'Казань'}; self.assertIsNone(classify(self.v,self.now)[0])
    def test_preliminary_missing(self):
        from job_monitor import preliminary
        self.assertIsNone(preliminary({},self.now))
    def test_preliminary_rotation(self):
        from job_monitor import preliminary
        self.assertEqual(preliminary({'type_of_work':{'title':'Вахта'}},self.now),'rotation')
    def test_region_query(self):
        from unittest.mock import patch
        from job_monitor import search
        with patch('job_monitor.api',side_effect=[{'objects':[{'id':4,'title':'Московская область'}]}]+[{'objects':[],'more':False}]*5) as m:
            self.assertEqual(search(),{})
            self.assertEqual(m.call_args_list[1].args[1]['o[]'],[4])
    def test_missing_region(self):
        from unittest.mock import patch
        from job_monitor import regions
        with patch('job_monitor.api',return_value={'objects':[]}):
            with self.assertRaises(RuntimeError): regions()
if __name__=='__main__': unittest.main()
