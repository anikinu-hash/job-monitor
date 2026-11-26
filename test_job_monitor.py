import unittest,time
from job_monitor import classify,fingerprint
class Tests(unittest.TestCase):
    def setUp(self):
        self.now=time.time(); self.v={'id':1,'profession':'Главный геодезист','firm_name':'Test','town':{'title':'Москва'},'address':'Москва','work':'Работа на объекте в Москве','type_of_work':{'title':'Полный рабочий день'},'date_published':int(self.now),'link':'https://www.superjob.ru/vakansii/test-1.html'}
    def test_valid(self): self.assertEqual(classify(self.v,self.now)[0],1)
    def test_rotation(self): self.v['work']='Вахта'; self.assertIsNone(classify(self.v,self.now)[0])
    def test_unknown_schedule(self): self.v['type_of_work']=''; self.assertIsNone(classify(self.v,self.now)[0])
    def test_unknown_site(self): self.v['address']=''; self.v['work']=''; self.assertIsNone(classify(self.v,self.now)[0])
    def test_old(self): self.v['date_published']-=800000; self.assertIsNone(classify(self.v,self.now)[0])
    def test_archive(self): self.v['is_archive']=True; self.assertIsNone(classify(self.v,self.now)[0])
    def test_duplicate(self): a=fingerprint(self.v); self.v['id']=2; self.assertEqual(a,fingerprint(self.v))
    def test_no_rotation(self): self.v['compensation']='Без вахты, 5/2'; self.assertEqual(classify(self.v,self.now)[0],1)
    def test_mixed_rotation(self): self.v['compensation']='Без вахты в Москве, возможна вахта'; self.assertIsNone(classify(self.v,self.now)[0])
    def test_suburb(self): self.v['town']={'title':'Химки'}; self.v['address']='Химки'; self.v['work']='Работа в Химки'; self.assertEqual(classify(self.v,self.now)[0],1)
    def test_outside(self): self.v['work']='Объект в Тульской области'; self.assertIsNone(classify(self.v,self.now)[0])
    def test_town_only(self): self.v['address']=''; self.v['work']=''; self.assertIsNone(classify(self.v,self.now)[0])
    def test_bad_town(self): self.v['town']={'title':'Казань'}; self.assertIsNone(classify(self.v,self.now)[0])
    def test_preliminary_missing(self):
        from job_monitor import preliminary
        self.assertIsNone(preliminary({},self.now))
    def test_preliminary_rotation(self):
        from job_monitor import preliminary
        self.assertIsNone(preliminary({'type_of_work':{'title':'Вахта'}},self.now))
    def test_region_query(self):
        from unittest.mock import patch
        from job_monitor import search
        with patch('job_monitor.api',side_effect=[{'objects':[{'id':46,'title':'Московская область','id_country':1}]},{'objects':[{'id':4,'title':'Москва','id_country':1}]}]+[{'objects':[],'more':False}]*20) as m:
            self.assertEqual(search(),{})
            self.assertEqual(m.call_args_list[2].args[1]['town'],4)
            self.assertEqual(m.call_args_list[12].args[1]['o[0]'],46)
    def test_duties(self):
        self.v['profession']='Инженер строительного контроля'; self.v['work']='Геодезический контроль на объекте в Москве'; self.assertIsNotNone(classify(self.v,self.now)[0])
    def test_rotation_id(self):
        self.v['type_of_work']={'id':9,'title':'Полный день'}; self.assertEqual(classify(self.v,self.now)[1],'rotation')
    def test_company_address_only(self):
        self.v['work']=''; self.assertIsNone(classify(self.v,self.now)[0])
    def test_full_day(self):
        self.v['type_of_work']={'id':6,'title':'Полный день'}; self.assertIsNotNone(classify(self.v,self.now)[0])
    def test_missing_region(self):
        from unittest.mock import patch
        from job_monitor import regions
        with patch('job_monitor.api',return_value={'objects':[]}):
            with self.assertRaises(RuntimeError): regions()
    def test_multiple_reasons(self):
        from job_monitor import evaluate
        self.v.update(profession='Менеджер',work='Вахта',town={'title':'Казань'})
        _, reasons, _=evaluate(self.v,self.now)
        self.assertTrue({'rotation','irrelevant','town unconfirmed','worksite unconfirmed'}.issubset(reasons))
    def test_requirements(self):
        from job_monitor import relevant
        self.assertTrue(relevant({'profession':'Инженер','candidat':'Опыт геодезических работ'}))
    def test_report(self):
        from unittest.mock import patch
        from job_monitor import main
        import tempfile, os, json
        from pathlib import Path
        old=os.getcwd()
        with tempfile.TemporaryDirectory() as d:
            try:
                os.chdir(d)
                with patch('job_monitor.search',return_value={'1':self.v}),patch('job_monitor.api',return_value=self.v): main()
                r=json.loads(Path('private-report/diagnostic.json').read_text())['records'][0]
                self.assertEqual(r['status'],'api_candidate')
                self.assertEqual(r['summary']['profession'],self.v['profession'])
            finally: os.chdir(old)
if __name__=='__main__': unittest.main()
