import os, json, re, time, ssl, smtplib, hashlib, sys
from datetime import datetime, timezone
from pathlib import Path
from urllib.request import Request, urlopen
from urllib.parse import urlencode, urlsplit
from urllib.error import HTTPError
from email.message import EmailMessage
from html import escape

API='https://api.superjob.ru/2.0/'
QUERIES=('геодезист','геодезический контроль','лазерное сканирование','облака точек','геодезия','главный геодезист','ведущий геодезист','технический заказчик','строительный контроль','главный специалист по геодезии')
MAX_AGE=7*86400
LIMIT=20
ROTATION=re.compile(r'вахт|межвахт',re.I)
REGION=re.compile(r'\bмоскв[аеуы]\b|московск\w*\s+област|подмосковь|\b(?:химки|балашиха|мытищи|красногорск|одинцово|люберцы|подольск|домодедово|реутов|долгопрудный|лобня|видное|котельники|пушкино|корол[её]в|щ[её]лково|электросталь|раменское|жуковский|истра|чехов|серпухов|дмитров|клин|солнечногорск|ногинск|коломна|воскресенск|ступино|наро-фоминск|сергиев посад|орехово-зуево)\b',re.I)
NEG_ROTATION=re.compile(r'без\s+вахт\w*|не\s+вахт\w*|вахт\w*\s+не\s+предусмотрен\w*',re.I)
OUTSIDE=re.compile(r'санкт-петербург|ленинградск\w*\s+област|тульск\w*\s+област|калужск\w*\s+област|тверск\w*\s+област|рязанск\w*\s+област|сахалин|якут|краснояр|сибир|хмао|янао|новосибирск|екатеринбург',re.I)
OTHER=re.compile(r'командиров|разъезд|объект[ыа]? по россии',re.I)

def field(v,k):
    x=v.get(k) or ''
    return str(x.get('title','') if isinstance(x,dict) else x)

def api(path,params=None):
    req=Request(API+path+('?' + urlencode(params,doseq=True) if params else ''),headers={'X-Api-App-Id':os.environ['SUPERJOB_API_KEY'],'Accept':'application/json','User-Agent':'JobMonitor/1.4'})
    for attempt in range(3):
        try:
            with urlopen(req,timeout=30) as r: return json.load(r)
        except HTTPError as e:
            if e.code not in (429,500,502,503,504) or attempt==2: raise RuntimeError(f'API HTTP {e.code}') from None
        time.sleep(2**attempt)

def evaluate(v, now):
    title=field(v,'profession'); duties=field(v,'work'); req=field(v,'candidat'); terms=field(v,'compensation'); schedule=field(v,'type_of_work'); town=field(v,'town'); address=field(v,'address')
    body=' '.join((title,duties,req,terms,schedule,address,field(v,'description')))
    reasons=[]
    if str((v.get('type_of_work') or {}).get('id','') if isinstance(v.get('type_of_work'),dict) else '')=='9' or ROTATION.search(NEG_ROTATION.sub('',body)): reasons.append('rotation')
    if v.get('is_archive') or v.get('archive') or v.get('is_closed'): reasons.append('closed')
    try: age=now-int(v['date_published'])
    except (KeyError,ValueError,TypeError): age=-1
    if not 0<=age<=MAX_AGE: reasons.append('date')
    if not relevant(v): reasons.append('irrelevant')
    if OUTSIDE.search(body+' '+town): reasons.append('outside or ambiguous region')
    if not REGION.search(town): reasons.append('town unconfirmed')
    # A company address or search city alone is not worksite evidence.
    site_text=' '.join((duties,terms,field(v,'description')))
    site_pattern=r'(?:место работы|работа на объекте|на объекте в|работа в|объект находится|объект расположен|объект в|адрес объекта|работа на территории)'
    evidence=[x for x in re.split(r'[\n;.!?]',site_text) if re.search(site_pattern,x,re.I) and REGION.search(x)]
    if not evidence: reasons.append('worksite unconfirmed')
    if OTHER.search(body): reasons.append('travel unconfirmed')
    if not re.search(r'полный (?:рабочий )?день|5\s*[/–-]\s*2|пятиднев|без вахты',schedule+' '+terms,re.I): reasons.append('schedule unconfirmed')
    if re.search(r'главн\w* геодезист|руководител\w* геодез',title,re.I): rank=1
    elif re.search(r'техническ\w* заказчик|техзаказчик',title+' '+duties,re.I): rank=2
    elif re.search(r'ведущ|главн|контрол',title,re.I): rank=3
    elif re.search(r'сканирован|облак',title,re.I): rank=4
    else: rank=5
    u=urlsplit(field(v,'link'))
    if u.scheme!='https' or not (u.hostname=='superjob.ru' or (u.hostname or '').endswith('.superjob.ru')): reasons.append('link')
    if not v.get('id'): reasons.append('id')
    return rank,reasons,evidence

def classify(v,now):
    rank,reasons,_=evaluate(v,now)
    return (None,reasons[0]) if reasons else (rank,'ok')

def fingerprint(v):
    def norm(s): return re.sub(r'\W+','',s.casefold())
    return hashlib.sha256('|'.join(norm(field(v,k)) for k in ('firm_name','profession','town','address')).encode()).hexdigest()

def relevant(v):
    title=field(v,'profession'); work=' '.join(field(v,k) for k in ('work','candidat','description','compensation'))
    pattern=r'геодез|лазерн\w*\s+сканирован|облак\w*\s+точек'
    return bool(re.search(pattern,title+' '+work,re.I))

def regions():
    rows=api('regions/',{'keyword':'Московская область','all':1}).get('objects',[])
    matches=[r for r in rows if field(r,'title').strip().casefold()=='московская область' and str(r.get('id_country'))=='1']
    if len(matches)!=1: raise RuntimeError('Moscow region not verified')
    return [matches[0]['id']]

def moscow():
    rows=api('towns/',{'keyword':'Москва','id_country':1,'all':1}).get('objects',[])
    matches=[r for r in rows if field(r,'title').strip().casefold()=='москва' and str(r.get('id_country'))=='1']
    if len(matches)!=1: raise RuntimeError('Moscow city not verified')
    return matches[0]['id']

def search():
    found={}
    region=regions()[0]; city=moscow()
    print('Verified directory: Moscow city',city,'Moscow region',region)
    for area,filters in [('Moscow',{'town':city}),('Moscow oblast',{'o[0]':region})]:
        for q in QUERIES:
            total_rows=0
            for page in range(5):
                data=api('vacancies/',{'keyword':q,'count':100,'page':page,'period':7,**filters})
                rows=data.get('objects')
                if not isinstance(rows,list): raise RuntimeError('Unexpected API response')
                total_rows+=len(rows)
                for v in rows:
                    if v.get('id'): found[str(v['id'])]=v
                if not data.get('more'): break
                if page==4: raise RuntimeError('Pagination limit reached; search incomplete')
            print('Query:',area,q,'rows:',total_rows,'API total:',data.get('total'))
    return found

def preliminary(v,now):
    if v.get('is_archive') or v.get('archive') or v.get('is_closed'): return 'closed'
    return None

def report(rows,counts):
    out=['<html lang="ru"><meta charset="utf-8"><h2>Job Monitor — SuperJob</h2>',f'<p>Дата: {datetime.now(timezone.utc).isoformat(timespec="minutes")} UTC. Найдено новых: {len(rows)}. Проверка по API; доступность кнопки отклика на сайте не проверена.</p>','<table border="1" cellpadding="6"><tr><th>Компания</th><th>Должность</th><th>Место</th><th>Зарплата</th><th>Требования и обязанности</th><th>График</th><th>Ссылка</th></tr>']
    for v in rows:
        salary=f"{v.get('payment_from') or '—'} – {v.get('payment_to') or '—'} {v.get('currency') or ''}; НДФЛ не уточнён"
        cells=[field(v,'firm_name'),field(v,'profession'),field(v,'town')+' '+field(v,'address'),salary,field(v,'candidat')+' / '+field(v,'work'),field(v,'type_of_work')]
        out.append('<tr>'+''.join('<td>'+escape(c)+'</td>' for c in cells)+'<td><a href="'+escape(field(v,'link'),quote=True)+'">Вакансия</a></td></tr>')
    out.append('</table><p>Исключения: '+escape(json.dumps(counts,ensure_ascii=False))+'</p></html>')
    return ''.join(out)

def send(html):
    msg=EmailMessage(); msg['Subject']='Job Monitor — ежедневный отчёт SuperJob'; msg['From']=os.environ['MAIL_USER']; msg['To']=os.environ['MAIL_TO']; msg.set_content('Отчёт в HTML-части письма.'); msg.add_alternative(html,subtype='html')
    with smtplib.SMTP_SSL('smtp.mail.ru',465,context=ssl.create_default_context(),timeout=30) as smtp:
        smtp.login(os.environ['MAIL_USER'],os.environ['MAIL_APP_PASSWORD']); smtp.send_message(msg)

def main():
    from collections import Counter
    now=time.time(); counts=Counter(); records=[]
    fields=('id','profession','work','candidat','compensation','description','town','address','type_of_work','firm_name','date_published','link','payment_from','payment_to','currency','is_archive','is_closed')
    def snapshot(v):
        return {k:v[k] for k in fields if k in v}
    for ident,summary in search().items():
        try: v=api('vacancies/'+ident+'/')
        except RuntimeError as e:
            if str(e) in ('API HTTP 404','API HTTP 410'):
                counts['closed']+=1; continue
            raise
        if str(v.get('id'))!=ident: raise RuntimeError('Unexpected detail ID')
        rank,reasons,evidence=evaluate(v,now)
        counts.update(reasons)
        hard={'rotation','closed','date','irrelevant','id','link'}
        status='excluded' if hard.intersection(reasons) else ('review' if reasons else 'api_candidate')
        records.append(dict(id=ident,rank=rank,status=status,reasons=reasons,worksite_evidence=evidence,summary=snapshot(summary),detail=snapshot(v),summary_keys=sorted(summary),detail_keys=sorted(v)))
    records.sort(key=lambda r:(r['status']!='api_candidate',r['rank'],r['id']))
    stats=Counter(r['status'] for r in records)
    out=Path('private-report'); out.mkdir(exist_ok=True)
    (out/'diagnostic.json').write_text(json.dumps({'version':'1.4','counts':dict(counts),'records':records},ensure_ascii=False,indent=2),encoding='utf-8')
    html=['<!doctype html><html lang="ru"><meta charset="utf-8"><h1>Job Monitor 1.4</h1><p>Кандидаты API не являются подтвержденными: доступность отклика не проверена. Причины могут пересекаться.</p>']
    for status,label in [('api_candidate','Кандидаты API (до 20)'),('review','Ручная проверка'),('excluded','Исключенные')]:
        html.append('<h2>'+label+'</h2><table border="1"><tr><th>Компания / должность</th><th>Город / адрес компании</th><th>График</th><th>Причины / признаки</th><th>Требования / обязанности</th><th>Ссылка</th></tr>')
        group=[r for r in records if r['status']==status]
        for r in (group[:20] if status=='api_candidate' else group):
            v=r['detail']; cells=[field(v,'firm_name')+' / '+field(v,'profession'),field(v,'town')+' / '+field(v,'address'),field(v,'type_of_work'),'; '.join(r['reasons']+r['worksite_evidence']),field(v,'candidat')+' / '+field(v,'work')]
            link=field(v,'link'); u=urlsplit(link); safe=u.scheme=='https' and (u.hostname=='superjob.ru' or (u.hostname or '').endswith('.superjob.ru'))
            html.append('<tr>'+''.join('<td>'+escape(c)+'</td>' for c in cells)+'<td>'+('<a href="'+escape(link,quote=True)+'">Открыть</a>' if safe else '—')+'</td></tr>')
        html.append('</table>')
    (out/'report.html').write_text(''.join(html)+'</html>',encoding='utf-8')
    print('Version 1.4; detail rows:',len(records),'statuses:',dict(stats),'reasons:',dict(counts))
    print('Confirmed website applications: 0 (not checked)')

if __name__=='__main__': main()
