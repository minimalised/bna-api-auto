#!/usr/bin/env python3
"""Naver Search Ads 광고그룹 조회·설정 변경·소재 삭제.

list       : 광고그룹 설정, 타게팅(매체·요일/시간대), 소재를 조회해 CSV/JSON으로 저장 (읽기 전용).
update     : 지정 그룹의 이름·ON/OFF·입찰가·일예산·타게팅을 바꾼다.
delete-ads : 지정 소재를 삭제한다 (복구 불가).
update/delete-ads는 기본이 미리보기(변경 전→후만 출력)이고, --apply를 줘야 실제 반영한 뒤
다시 조회해 결과를 확인한다. 인증·서명은 naver_report.Client를 그대로 쓴다.
"""
import argparse
import csv
import json
import os
import sys
from datetime import datetime
from pathlib import Path

from naver_report import KST, TYPES, Client, Collector, env

TARGET_TYPES = ('MEDIA_TARGET', 'TIME_WEEKLY_TARGET')
LOCK = {'on': True, 'off': False}

COLUMNS = ['계정ID', '캠페인ID', '캠페인', '캠페인 유형', '광고그룹ID', '광고그룹', '상태',
           'ON/OFF', '기본입찰가', '일예산 사용', '일예산', 'PC 입찰가중치', '모바일 입찰가중치', '수정시각']


def customers():
    owner = env('NAVER_CUSTOMER_ID')
    return list(dict.fromkeys(c.strip() for c in env('NAVER_CUSTOMER_IDS', owner).split(',') if c.strip()))


def summarize(customer, camp, g):
    return {
        '계정ID': customer,
        '캠페인ID': g.get('nccCampaignId', ''),
        '캠페인': camp.get('name', ''),
        '캠페인 유형': TYPES.get(camp.get('campaignTp', ''), camp.get('campaignTp', '')),
        '광고그룹ID': g.get('nccAdgroupId', ''),
        '광고그룹': g.get('name', ''),
        '상태': g.get('status', ''),
        'ON/OFF': 'OFF' if g.get('userLock') else 'ON',
        '기본입찰가': g.get('bidAmt', ''),
        '일예산 사용': g.get('useDailyBudget', ''),
        '일예산': g.get('dailyBudget', ''),
        'PC 입찰가중치': g.get('pcNetworkBidWeight', ''),
        '모바일 입찰가중치': g.get('mobileNetworkBidWeight', ''),
        '수정시각': g.get('editTm', ''),
    }


def targets(client, customer, gid):
    t = client.get('/ncc/targets', customer, {'ownerId': gid, 'types': ','.join(TARGET_TYPES)})
    return {x.get('targetTp'): x for x in t} if isinstance(t, list) else {}


def ads(client, customer, gid):
    a = client.get('/ncc/ads', customer, {'nccAdgroupId': gid})
    return a if isinstance(a, list) else []


def ad_text(ad):
    a = ad.get('ad') or {}
    return ' / '.join(str(a[k]) for k in ('headline', 'description', 'productName') if a.get(k)) or ad.get('type', '')


def load_all(client):
    out = []
    for customer in customers():
        c = Collector(client, customer)
        c.load_groups()
        for cid, err in c.group_errors.items():
            print(f'[경고] {customer} 캠페인 {cid} 광고그룹 조회 실패: {err}', file=sys.stderr)
        for g in c.groups.values():
            out.append((customer, c.campaigns.get(g.get('nccCampaignId'), {}), g))
    return out


def cmd_list(client, args):
    rows, ad_rows, detail = [], [], []
    for customer, camp, g in load_all(client):
        gid = g['nccAdgroupId']
        t, a = targets(client, customer, gid), ads(client, customer, gid)
        rows.append(summarize(customer, camp, g))
        detail.append({'customer': customer, 'campaign': camp.get('name', ''), 'adgroup': g, 'targets': t, 'ads': a})
        for ad in a:
            ad_rows.append({'캠페인': camp.get('name', ''), '광고그룹': g.get('name', ''), '광고그룹ID': gid,
                            '소재ID': ad.get('nccAdId', ''), '유형': ad.get('type', ''),
                            'ON/OFF': 'OFF' if ad.get('userLock') else 'ON', '상태': ad.get('status', ''),
                            '내용': ad_text(ad)})
    rows.sort(key=lambda r: (r['계정ID'], r['캠페인 유형'], r['캠페인'], r['광고그룹']))
    outdir = Path('reports')
    outdir.mkdir(exist_ok=True)
    stamp = f'{datetime.now(KST):%Y%m%dT%H%M%S}'
    write_csv(outdir / f'naver_adgroups_{stamp}.csv', COLUMNS, rows)
    write_csv(outdir / f'naver_ads_{stamp}.csv', list(ad_rows[0]) if ad_rows else ['소재ID'], ad_rows)
    (outdir / f'naver_adgroups_detail_{stamp}.json').write_text(
        json.dumps(detail, ensure_ascii=False, indent=1), encoding='utf-8')
    print('## 광고그룹\n')
    print(markdown(rows, ['캠페인 유형', '캠페인', '광고그룹', '광고그룹ID', 'ON/OFF', '기본입찰가', '일예산 사용', '일예산']))
    print('\n## 타게팅 (원본)\n')
    for d in detail:
        g = d['adgroup']
        print(f"- {d['campaign']} / {g.get('name')} ({g['nccAdgroupId']})")
        for tp in TARGET_TYPES:
            print(f"  - {tp}: `{json.dumps((d['targets'].get(tp) or {}).get('target'), ensure_ascii=False)}`")
    print('\n## 소재\n')
    if ad_rows:
        print(markdown(ad_rows, list(ad_rows[0])))
    print(f'\n광고그룹 {len(rows)}개, 소재 {len(ad_rows)}개. 파일: reports/*_{stamp}.*')
    return 0


def write_csv(path, fields, rows):
    with open(path, 'w', newline='', encoding='utf-8-sig') as f:
        w = csv.DictWriter(f, fields)
        w.writeheader()
        w.writerows(rows)


def markdown(rows, cols):
    lines = ['| ' + ' | '.join(cols) + ' |', '|' + '---|' * len(cols)]
    lines += ['| ' + ' | '.join(str(r[c]).replace('|', '/') for c in cols) + ' |' for r in rows]
    return '\n'.join(lines)


def plan_changes(g, args):
    """Return (fields, new_obj, diffs) for one ad group."""
    new = dict(g)
    fields, diffs = [], []

    def change(field, key, value):
        if g.get(key) != value:
            new[key] = value
            diffs.append((key, g.get(key), value))
            if field not in fields:
                fields.append(field)

    if args.name:
        change('', 'name', args.name)
    if args.lock:
        change('userLock', 'userLock', LOCK[args.lock])
    if args.bid_amt is not None:
        if args.bid_amt < 70 or args.bid_amt % 10:
            raise ValueError('기본입찰가는 70원 이상, 10원 단위여야 합니다.')
        change('bidAmt', 'bidAmt', args.bid_amt)
    if args.daily_budget is not None:
        if args.daily_budget == 'off':
            change('budget', 'useDailyBudget', False)
        else:
            amount = int(args.daily_budget)
            if amount < 50 or amount % 10:
                raise ValueError('일예산은 50원 이상, 10원 단위여야 합니다.')
            change('budget', 'useDailyBudget', True)
            change('budget', 'dailyBudget', amount)
    for item in args.set or []:
        # 고급: --set fieldsName:key=JSON (API 문서의 fields 이름과 객체 키를 직접 지정)
        try:
            field, rest = item.split(':', 1)
            key, raw = rest.split('=', 1)
            value = json.loads(raw)
        except ValueError:
            raise ValueError(f'--set 형식 오류: {item} (예: budget:dailyBudget=30000)') from None
        change(field, key, value)
    return fields, new, diffs


def cmd_update(client, args):
    ids = [x.strip() for x in args.ids.split(',') if x.strip()]
    if not ids:
        raise ValueError('--ids에 광고그룹ID를 하나 이상 입력하세요.')
    found = {g['nccAdgroupId']: (cust, camp, g) for cust, camp, g in load_all(client)}
    if args.name and len(ids) > 1:
        raise ValueError('이름 변경은 광고그룹 1개씩만 할 수 있습니다.')
    missing = [i for i in ids if i not in found]
    if missing:
        raise ValueError(f'찾을 수 없는 광고그룹ID: {", ".join(missing)}')
    target_new = {}
    for item in args.target or []:
        tp, _, raw = item.partition('=')
        if tp not in TARGET_TYPES:
            raise ValueError(f'--target 유형은 {", ".join(TARGET_TYPES)} 중 하나여야 합니다.')
        try:
            target_new[tp] = json.loads(raw)
        except ValueError:
            raise ValueError(f'--target {tp} 값이 JSON이 아닙니다.') from None
    plans = []
    for gid in ids:
        cust, camp, g = found[gid]
        fields, new, diffs = plan_changes(g, args)
        tchanges = []
        if target_new:
            cur = targets(client, cust, gid)
            for tp, value in target_new.items():
                if tp not in cur:
                    raise ValueError(f'{gid}에 {tp} 타게팅이 없습니다.')
                if cur[tp].get('target') != value:
                    tchanges.append((cur[tp], value))
        plans.append((cust, camp, g, fields, new, diffs, tchanges))
        print(f'\n[{camp.get("name", "")}] {g.get("name", "")} ({gid})')
        if not diffs and not tchanges:
            print('  변경 없음 (이미 같은 값)')
        for key, old, value in diffs:
            print(f'  {key}: {old} → {value}')
        for t, value in tchanges:
            print(f'  {t["targetTp"]}: {json.dumps(t.get("target"), ensure_ascii=False)}')
            print(f'    → {json.dumps(value, ensure_ascii=False)}')
    todo = [p for p in plans if p[5] or p[6]]
    if not todo:
        print('\n바꿀 내용이 없습니다.')
        return 0
    if not args.apply:
        print(f'\n미리보기만 했습니다. 실제 반영하려면 apply를 켜고 다시 실행하세요. (대상 {len(todo)}개)')
        return 0
    failed = 0
    for cust, camp, g, fields, new, diffs, tchanges in todo:
        gid = g['nccAdgroupId']
        try:
            bad = []
            if diffs:
                # 이름 변경은 fields 없이 전체 객체 수정, 나머지는 해당 fields만 수정
                params = {'fields': ','.join(f for f in fields if f)} if all(fields) else None
                client.request('PUT', f'/ncc/adgroups/{gid}', cust, params=params, body=new)
                after = client.get(f'/ncc/adgroups/{gid}', cust)
                bad += [(k, v, after.get(k)) for k, _, v in diffs if after.get(k) != v]
            for t, value in tchanges:
                client.request('PUT', f'/ncc/targets/{t["nccTargetId"]}', cust, body={**t, 'target': value})
            if tchanges:
                cur = targets(client, cust, gid)
                bad += [(t['targetTp'], v, (cur.get(t['targetTp']) or {}).get('target'))
                        for t, v in tchanges if (cur.get(t['targetTp']) or {}).get('target') != v]
            if bad:
                failed += 1
                print(f'[확인 실패] {g.get("name")} ({gid}): ' +
                      ', '.join(f'{k} 기대 {v}, 실제 {a}' for k, v, a in bad))
            else:
                print(f'[반영 완료] {g.get("name")} ({gid})')
        except Exception as e:
            failed += 1
            print(f'[실패] {g.get("name")} ({gid}): {e}')
    return 1 if failed else 0


def cmd_delete_ads(client, args):
    ids = [x.strip() for x in args.ad_ids.split(',') if x.strip()]
    if not ids:
        raise ValueError('--ad-ids에 소재ID를 하나 이상 입력하세요.')
    cust = args.customer or customers()[0]
    found = []
    for aid in ids:
        ad = client.get(f'/ncc/ads/{aid}', cust)
        found.append(ad)
        print(f'- {aid} [{ad.get("nccAdgroupId")}] {ad.get("type")}: {ad_text(ad)}')
    if not args.apply:
        print(f'\n미리보기만 했습니다. 위 {len(found)}개 소재를 삭제하려면 apply를 켜고 다시 실행하세요. (복구 불가)')
        return 0
    failed = 0
    for ad in found:
        aid = ad['nccAdId']
        try:
            client.request('DELETE', f'/ncc/ads/{aid}', cust)
            print(f'[삭제 완료] {aid}')
        except Exception as e:
            failed += 1
            print(f'[실패] {aid}: {e}')
    return 1 if failed else 0


def main():
    p = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = p.add_subparsers(dest='cmd', required=True)
    sub.add_parser('list', help='광고그룹 현재 설정 조회')
    u = sub.add_parser('update', help='광고그룹 설정 변경 (기본 미리보기)')
    u.add_argument('--ids', required=True, help='광고그룹ID, 쉼표 구분')
    u.add_argument('--name', help='새 광고그룹 이름')
    u.add_argument('--target', action='append',
                   help='타게팅 교체: MEDIA_TARGET=JSON 또는 TIME_WEEKLY_TARGET=JSON (list 결과 형식 그대로)')
    u.add_argument('--lock', choices=['on', 'off'], help='on=그룹 OFF(일시중지), off=그룹 ON')
    u.add_argument('--bid-amt', type=int, help='기본입찰가(원)')
    u.add_argument('--daily-budget', help="일예산(원) 또는 'off'(제한 없음)")
    u.add_argument('--set', action='append', help='고급: fields이름:키=JSON값')
    u.add_argument('--apply', action='store_true', help='실제 반영 (없으면 미리보기)')
    d = sub.add_parser('delete-ads', help='소재 삭제 (기본 미리보기, 복구 불가)')
    d.add_argument('--ad-ids', required=True, help='소재ID, 쉼표 구분')
    d.add_argument('--customer', help='계정ID (기본: NAVER_CUSTOMER_IDS 첫 번째)')
    d.add_argument('--apply', action='store_true', help='실제 삭제 (없으면 미리보기)')
    args = p.parse_args()
    client = Client()
    return {'list': cmd_list, 'update': cmd_update, 'delete-ads': cmd_delete_ads}[args.cmd](client, args)


if __name__ == '__main__':
    try:
        sys.exit(main())
    except ValueError as e:
        print(f'오류: {e}', file=sys.stderr)
        sys.exit(2)
