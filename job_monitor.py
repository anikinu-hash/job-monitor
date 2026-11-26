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
REGION=re.compile(r'\bмоскв[аеуы]\b|московск\w*\s+област|подмосковь|\b(?:химки|балашиха|мытищи|красногорск|одинцово|люберцы|подольск|домодедово|реутов|долгопрудный|лобня|видное|котельники|пушкино|корол[её]в|щ[её]лково|электросталь|раменское|жуковский|истра|чехов|серпухов|дмитров|клин|солнечногорск|ногинск|коломна|воскресенск|ступино|наро-фоминск|сергиев посад|орехово-зуево)\b',re.I)
NEG_ROTATION=re.compile(r'без\s+вахт\w*|не\s+вахт\w*|вахт\w*\s+не\s+предусмотрен\w*',re.I)
OUTSIDE=re.compile(r'санкт-петербург|ленинградск\w*\s+област|тульск\w*\s+област|калужск\w*\s+област|тверск\w*\s+област|рязанск\w*\s+област|сахалин|якут|краснояр|сибир|хмао|янао|новосибирск|екатеринбург',re.I)
OTHER=re.compile(r'командиров|разъезд|объект[ыа]? по россии',re.I)

def field(v,k):
    x=v.get(k) or ''
    return str(x.get('title','') if isinstance(x,dict) else x)

def api(path,params=None):
    req=Request(API+path+('?' + urlencode(params,doseq=True) if params else ''),headers={'X-Api-App-Id':os.environ['SUPERJOB_API_KEY'],'Accept':'application/json','User-Agent':'JobMonitor/1.2'})
    for attempt in range(3):
        try:
            with urlopen(req,timeout=30) as r: return json.load(r)
        except HTTPError as e:
            if e.code not in (429,500,502,503,504) or attempt==2: raise RuntimeError(f'API HTTP {e.code}') from None
        time.sleep(2**attempt)

def classify(v,now):
    title=field(v,'profession'); duties=field(v,'work'); req=field(v,'candidat'); terms=field(v,'compensation'); schedule=field(v,'type_of_work'); town=field(v,'town'); address=field(v,'address'); body=' '.join((title,duties,req,terms,schedule,address))
    if ROTATION.search(NEG_ROTATION.sub('',body)): return None,'rotation'
    if v.get('is_archive') or v.get('archive') or v.get('is_closed'): return None,'closed'
    try: age=now-int(v['date_published'])
    except (KeyError,ValueError,TypeError): return None,'date'
    if not 0<=age<=MAX_AGE: return None,'date'
    # Conservative: city alone is not proof of actual worksite.
    if OUTSIDE.search(body+' '+town): return None,'outside or ambiguous region'
    if not REGION.search(town): return None,'town unconfirmed'
    if not REGION.search(address+' '+duties+' '+terms): return None,'worksite unconfirmed'
    if address and not REGION.search(address) and not REGION.search(duties+' '+terms): return None,'worksite unconfirmed'
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

def regions():
    data=api('regions/',{'count':100})
    rows=data.get('objects')
    if not isinstance(rows,list): raise RuntimeError('Region directory unavailable')
    matches=[r for r in rows if field(r,'title').casefold().strip() in ('москва','московская область')]
    if not any(field(r,'title').casefold().strip()=='московская область' for r in matches):
        raise RuntimeError('Moscow region not verified in directory')
    return [r['id'] for r in matches]

def search():
    found={}
    region_ids=regions()
    print('Region directory IDs:',region_ids)
    for q in QUERIES:
        for page in range(10):
            data=api('vacancies/',{'keyword':q,'count':100,'page':page,'o[]':region_ids})
            rows=data.get('objects')
            if not isinstance(rows,list): raise RuntimeError('Unexpected API response')
            for v in rows:
                if v.get('id'): found[str(v['id'])]=v
            if not data.get('more'): break
            if page==9: raise RuntimeError('Pagination limit reached; search incomplete')
    return found

def preliminary(v,now):
    title=field(v,'profession')
    if title and not re.search(r'геодез|лазерн.*сканирован|облак[ао] точек',title,re.I): return 'irrelevant'
    if ROTATION.search(NEG_ROTATION.sub('',field(v,'type_of_work'))): return 'rotation'
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
    state=Path(os.environ.get('STATE_FILE','history.json')); seen=json.loads(state.read_text()) if state.exists() else {'ids':[],'fingerprints':[]}; ids=set(seen['ids']); fps=set(seen['fingerprints']); counts={}; candidates=[]; review=[]; now=time.time()
    stats={'search_rows':0,'detail_rows':0,'town_present':0,'address_present':0,'local_town':0,'local_address':0,'schedule_present':0,'town_region_match':0,'local_town_without_local_address':0}
    for ident,summary in search().items():
        stats['search_rows']+=1
        if ident in ids: continue
        reason=preliminary(summary,now)
        if reason:
            counts[reason]=counts.get(reason,0)+1; continue
        try: v=api('vacancies/'+ident+'/')
        except RuntimeError as e:
            if str(e)=='API HTTP 404':
                counts['closed']=counts.get('closed',0)+1; continue
            raise
        if str(v.get('id'))!=ident: raise RuntimeError('Unexpected detail ID')
        stats['detail_rows']+=1
        town=field(v,'town'); address=field(v,'address')
        for k,flag in [('town_present',bool(town)),('address_present',bool(address)),('local_town',bool(REGION.search(town))),('local_address',bool(REGION.search(address))),('schedule_present',bool(field(v,'type_of_work'))),('town_region_match',bool(REGION.search(field(v,'town')))),('local_town_without_local_address',bool(REGION.search(town)) and not bool(REGION.search(address)))]:
            stats[k]+=int(flag)
        rank,reason=classify(v,now)
        if rank is None:
            counts[reason]=counts.get(reason,0)+1
            if reason in ('town unconfirmed','worksite unconfirmed','outside or ambiguous region','schedule unconfirmed','travel unconfirmed'):
                review.append((ident,reason))
            continue
        candidates.append((rank,-int(v['date_published']),ident,v))
    selected=[]
    for _,_,ident,v in sorted(candidates):
        if len(selected)>=LIMIT: break
        fp=fingerprint(v)
        if fp in fps: continue
        selected.append(v); ids.add(ident); fps.add(fp)
    print('Diagnostics:',json.dumps(stats,ensure_ascii=False))
    print('Needs manual review (count only):',len(review))
    print('Exclusions:',json.dumps(counts,ensure_ascii=False))
    html=report(selected,counts)
    if os.environ.get('SEND_MAIL')!='1':
        print('Dry run: selected',len(selected),'exclusions',counts); return
    raise RuntimeError('Version 1.2 diagnostic only: email disabled')
    send(html)
    state.parent.mkdir(parents=True,exist_ok=True); tmp=state.with_suffix('.tmp'); tmp.write_text(json.dumps({'ids':sorted(ids),'fingerprints':sorted(fps)})); tmp.replace(state)
    print('Report sent; count:',len(selected))

if __name__=='__main__': main()
