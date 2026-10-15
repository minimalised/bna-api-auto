"""브랜드검색 계약 비용이 비즈머니 소진 내역에 잡히는지 확인 (읽기 전용)."""
import collections
from datetime import date, datetime, timedelta, timezone
from naver_report import Client, env

KST = timezone(timedelta(hours=9))
c = Client()
owner = env('NAVER_CUSTOMER_ID')
customers = list(dict.fromkeys(x.strip() for x in env('NAVER_CUSTOMER_IDS', owner).split(',') if x.strip()))

for cu in customers:
    print(f'===== 계정 {cu[-4:]} =====')
    start = date(2026, 4, 1)
    while start < date(2026, 10, 15):
        end = min(start + timedelta(days=30), date(2026, 10, 14))
        try:
            rows = c.get('/billing/bizmoney/histories/exhaust', cu,
                         {'searchStartDt': start.strftime('%Y%m%d'), 'searchEndDt': end.strftime('%Y%m%d')})
        except Exception as e:
            print(f'[FAIL] {start}~{end}: {e}')
            start = end + timedelta(days=1)
            continue
        agg = collections.defaultdict(float)
        days = collections.defaultdict(set)
        for r in rows:
            k = (r.get('campaignTp'), r.get('prodInfoCd'), r.get('activityCd'))
            agg[k] += (r.get('useRefundableAmt') or 0) + (r.get('useNonrefundableAmt') or 0)
            days[k].add(datetime.fromtimestamp(r['settleDt'] / 1000, KST).strftime('%m-%d'))
        print(f'-- {start}~{end}: {len(rows)}건, 키 목록 {sorted(set(k for r in rows for k in r))}')
        for k, v in sorted(agg.items(), key=lambda x: str(x[0])):
            d = sorted(days[k])
            print(f'   campaignTp={k[0]} prod={k[1]} activity={k[2]}: {round(v):,}원, {len(d)}일 ({d[0]}~{d[-1]})')
        start = end + timedelta(days=1)
