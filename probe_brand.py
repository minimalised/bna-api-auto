"""브랜드검색 계약 정보가 검색광고 API로 조회되는지 확인 (읽기 전용)."""
import json
from naver_report import Client, env

c = Client()
owner = env('NAVER_CUSTOMER_ID')
customers = list(dict.fromkeys(x.strip() for x in env('NAVER_CUSTOMER_IDS', owner).split(',') if x.strip()))

def show(label, fn):
    try:
        r = fn()
        s = json.dumps(r, ensure_ascii=False)
        print(f'[OK] {label}: {s[:3000]}')
        return r
    except Exception as e:
        print(f'[FAIL] {label}: {e}')

for cu in customers:
    print(f'===== 계정 {cu[-4:]} =====')
    camps = show('campaigns(BRAND_SEARCH)', lambda: [x for x in c.get('/ncc/campaigns', cu) if x.get('campaignTp') == 'BRAND_SEARCH'])
    for camp in camps or []:
        cid = camp['nccCampaignId']
        groups = show(f'adgroups {camp.get("name")}', lambda: c.get('/ncc/adgroups', cu, {'nccCampaignId': cid}))
        for g in (groups or [])[:5]:
            gid = g['nccAdgroupId']
            show(f'ads {g.get("name")}', lambda: c.get('/ncc/ads', cu, {'nccAdgroupId': gid}))
        show(f'stats {camp.get("name")}', lambda: c.get('/stats', cu, {
            'id': cid, 'fields': json.dumps(['impCnt', 'clkCnt', 'salesAmt']),
            'timeRange': json.dumps({'since': '2026-09-01', 'until': '2026-10-14'})}))
    show('bizmoney', lambda: c.get('/billing/bizmoney', cu))
    show('bizmoney exhaust', lambda: c.get('/billing/bizmoney/histories/exhaust', cu,
         {'searchStartDt': '20260901', 'searchEndDt': '20261014'}))
    show('bizmoney charge', lambda: c.get('/billing/bizmoney/histories/charge', cu,
         {'searchStartDt': '20260901', 'searchEndDt': '20261014'}))
