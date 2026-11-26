import json
from job_monitor import search, field, relevant
from collections import Counter

def main():
    rows=search(); counts=Counter()
    for v in rows.values():
        counts['rows']+=1
        for k in ('profession','work','candidat','town','type_of_work','address'):
            counts[k+'_present']+=bool(field(v,k))
        counts['title_match']+=relevant({'profession':field(v,'profession')})
        counts['title_or_duties_match']+=relevant(v)
        counts['expanded_search']+=bool(v.get('extended_search_parameters'))
    print('Summary field diagnostics:',json.dumps(counts,ensure_ascii=False))
if __name__=='__main__': main()
