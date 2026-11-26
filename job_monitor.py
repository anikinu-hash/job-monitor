import os, json, re, time, ssl, smtplib, hashlib, sys
from datetime import datetime, timezone
from pathlib import Path
from urllib.request import Request, urlopen
from urllib.parse import urlencode, urlsplit
from urllib.error import HTTPError
from email.message import EmailMessage
from html import escape

API='https://api.superjob.ru/2.0/'
QUERIES=('геодезист','геодезический контроль','лазерное сканирование','облака точек','геодезия')
MAX_AGE=7*86400
LIMIT=20
ROTATION=re.compile(r'вахт|межвахт',re.I)
REGION=re.compile(r'москва|московская область|подмосковье',re.I)
OTHER=re.compile(r'командиров|разъезд|объект[ыа]? по россии',re.I)

def field(v,k):
    x=v.get(k) or ''
    return str(x.get('title','') if isinstance(x,dict) else x)

def api(path,params=None):
    req=Request(API+path+('?' + urlencode(params,doseq=True) if params else ''),headers={'X-Api-App-Id':os.environ['SUPERJOB_API_KEY'],'Accept':'application/json','User-Agent':'JobMonitor/1.0'})
    for attempt in range(3):
        try:
            with urlopen(req,timeout=30) as r: return json.load(r)
        except HTTPError as e:
            if e.code not in (429,500,502,503,504) or attempt==2: raise RuntimeError(f'API HTTP {e.code}') from None
        time.sleep(2**attempt)

def classify(v,now):
    title=field(v,'profession'); duties=field(v,'work'); req=field(v,'candidat'); terms=field(v,'compensation'); schedule=field(v,'type_of_work'); town=field(v,'town'); address=field(v,'address'); body=' '.join((title,duties,req,terms,schedule,address))
    if ROTATION.search(body): return None,'rotation'
    if v.get('is_archive') or v.get('archive') or v.get('is_closed'): return None,'closed'
    try: age=now-int(v['date_published'])
    except (KeyError,ValueError,TypeError): return None,'date'
    if not 0<=age<=MAX_AGE: return None,'date'
    # Conservative: city alone is not proof of actual worksite.
    if not REGION.search(address+' '+duties+' '+terms): return None,'worksite unconfirmed'
    if OTHER.search(body): return None,'travel unconfirmed'
    if not re.search(r'полный рабочий день|5\s*[/–-]\s*2|пятиднев|без вахты',schedule+' '+terms,re.I): return None,'schedule unconfirmed'
    if not re.search(r'геодез|лазерн.*сканирован|облак[ао] точек',title,re.I): return None,'irrelevant'
    if not re.search(r'геодез|сканирован|облак',title,re.I): return None,'irrelevant'
    if re.search(r'главн\w* геодезист|руководител\w* геодез',title,re.I): rank=1
    elif re.search(r'техническ\w* заказчик|техзаказчик',title+' '+duties,re.I): rank=2
    elif re.search(r'ведущ|главн|контрол',title,re.I): rank=3
    elif re.search(r'сканирован|облак',title,re.I): rank=4
    else: rank=5
    link=field(v,'link'); u=urlsplit(link)
    if u.scheme!='https' or not (u.hostname=='superjob.ru' or (u.hostname or '').endswith('.superjob.ru')): return None,'link'
    if not v.get('id'): return None,'id'
    return rank,'ok'

def fingerprint(v):
    def norm(s): return re.sub(r'\W+','',s.casefold())
    return hashlib.sha256('|'.join(norm(field(v,k)) for k in ('firm_name','profession','town','address')).encode()).hexdigest()

def search():
    found={}
    for q in QUERIES:
        for page in range(10):
            data=api('vacancies/',{'keyword':q,'count':100,'page':page})
            rows=data.get('objects')
            if not isinstance(rows,list): raise RuntimeError('Unexpected API response')
            for v in rows:
                if v.get('id'): found[str(v['id'])]=v
            if not data.get('more'): break
            if page==9: raise RuntimeError('Pagination limit reached; search incomplete')
    return found

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
    state=Path(os.environ.get('STATE_FILE','history.json')); seen=json.loads(state.read_text()) if state.exists() else {'ids':[],'fingerprints':[]}; ids=set(seen['ids']); fps=set(seen['fingerprints']); counts={}; candidates=[]; now=time.time()
    for ident,v in search().items():
        if ident in ids: continue
        rank,reason=classify(v,now)
        if rank is None: counts[reason]=counts.get(reason,0)+1; continue
        candidates.append((rank,-int(v['date_published']),ident))
    selected=[]
    for _,_,ident in sorted(candidates):
        if len(selected)>=LIMIT: break
        try: v=api('vacancies/'+ident+'/')
        except RuntimeError as e:
            if str(e)=='API HTTP 404': continue
            raise
        rank,reason=classify(v,now)
        if rank is None: counts[reason]=counts.get(reason,0)+1; continue
        fp=fingerprint(v)
        if fp in fps: continue
        selected.append(v); ids.add(ident); fps.add(fp)
    html=report(selected,counts)
    if os.environ.get('SEND_MAIL')!='1':
        print('Dry run: selected',len(selected),'exclusions',counts); return
    send(html)
    state.parent.mkdir(parents=True,exist_ok=True); tmp=state.with_suffix('.tmp'); tmp.write_text(json.dumps({'ids':sorted(ids),'fingerprints':sorted(fps)})); tmp.replace(state)
    print('Report sent; count:',len(selected))

if __name__=='__main__': main()
