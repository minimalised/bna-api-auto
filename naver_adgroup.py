#!/usr/bin/env python3
"""Naver Search Ads 광고그룹 조회·설정 변경·소재 삭제.

list       : 광고그룹 설정, 타게팅(매체·요일/시간대), 소재를 조회해 CSV/JSON으로 저장 (읽기 전용).
rename     : 광고그룹 이름만 바꾼다 (1개씩).
media      : 매체 타게팅만 바꾼다.
schedule   : 요일·시간대 타게팅만 바꾼다 (네이버는 요일과 시간대가 한 설정).
delete-ads : 지정 소재를 삭제한다 (복구 불가).
한 번 실행에 한 가지 설정만 바꾸며, 반영 후 다시 조회해 그 설정 외 값이 그대로인지 확인한다.
rename/media/schedule/delete-ads는 기본이 미리보기(변경 전→후만 출력)이고, --apply를 줘야 실제 반영한 뒤
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


# 실행마다 바꾸는 값이 바뀌었는지, 그 외 값은 그대로인지 재조회로 확인할 때 무시하는 키
VOLATILE = {'editTm', 'status', 'statusReason', 'delFlag'}


def other_changes(before, after, key):
    return [k for k in set(before) | set(after)
            if k != key and k not in VOLATILE and before.get(k) != after.get(k)]


def find_groups(client, raw):
    ids = [x.strip() for x in raw.split(',') if x.strip()]
    if not ids:
        raise ValueError('광고그룹ID를 하나 이상 입력하세요.')
    found = {g['nccAdgroupId']: (cust, camp, g) for cust, camp, g in load_all(client)}
    missing = [i for i in ids if i not in found]
    if missing:
        raise ValueError(f'찾을 수 없는 광고그룹ID: {", ".join(missing)}')
    return [found[i] for i in ids]


def cmd_rename(client, args):
    """광고그룹 이름만 바꾼다."""
    if not args.name.strip():
        raise ValueError('새 이름을 입력하세요.')
    if ',' in args.id:
        raise ValueError('이름 변경은 광고그룹 1개씩만 할 수 있습니다.')
    [(cust, camp, g)] = find_groups(client, args.id)
    gid = g['nccAdgroupId']
    print(f'[{camp.get("name", "")}] {gid}\n  이름: {g.get("name")} → {args.name}')
    if g.get('name') == args.name:
        print('\n이미 같은 이름입니다.')
        return 0
    if not args.apply:
        print('\n미리보기만 했습니다. 실제 반영하려면 apply를 켜고 다시 실행하세요.')
        return 0
    # 방금 조회한 객체에서 이름만 바꿔 보내고, 다시 조회해 이름 외 값이 그대로인지 확인
    client.request('PUT', f'/ncc/adgroups/{gid}', cust, body={**g, 'name': args.name})
    after = client.get(f'/ncc/adgroups/{gid}', cust)
    return verify(g, after, 'name', args.name, g.get('name'))


def cmd_target(client, args):
    """매체 또는 요일·시간대 타게팅 하나만 바꾼다."""
    tp = {'media': 'MEDIA_TARGET', 'schedule': 'TIME_WEEKLY_TARGET'}[args.cmd]
    try:
        value = json.loads(args.target)
    except ValueError:
        raise ValueError('타게팅 값이 JSON이 아닙니다. list 결과 형식을 그대로 고쳐 넣어 주세요.') from None
    plans = []
    for cust, camp, g in find_groups(client, args.ids):
        cur = targets(client, cust, g['nccAdgroupId'])
        if tp not in cur:
            raise ValueError(f'{g["nccAdgroupId"]}에 {tp} 타게팅이 없습니다.')
        t = cur[tp]
        print(f'\n[{camp.get("name", "")}] {g.get("name", "")} ({g["nccAdgroupId"]})')
        if t.get('target') == value:
            print('  변경 없음 (이미 같은 값)')
            continue
        print(f'  {tp}: {json.dumps(t.get("target"), ensure_ascii=False)}')
        print(f'    → {json.dumps(value, ensure_ascii=False)}')
        plans.append((cust, g, cur))
    if not plans:
        print('\n바꿀 내용이 없습니다.')
        return 0
    if not args.apply:
        print(f'\n미리보기만 했습니다. 실제 반영하려면 apply를 켜고 다시 실행하세요. (대상 {len(plans)}개)')
        return 0
    failed = 0
    for cust, g, cur in plans:
        t = cur[tp]
        try:
            client.request('PUT', f'/ncc/targets/{t["nccTargetId"]}', cust, body={**t, 'target': value})
            after = targets(client, cust, g['nccAdgroupId'])
            before = {k: v.get('target') for k, v in cur.items()}
            failed += verify(before, {k: v.get('target') for k, v in after.items()}, tp, value,
                             t.get('target'), label=f'{g.get("name")} ({g["nccAdgroupId"]})')
        except Exception as e:
            failed += 1
            print(f'[실패] {g.get("name")} ({g["nccAdgroupId"]}): {e}')
    return 1 if failed else 0


def verify(before, after, key, expected, old, label=None):
    label = label or f'{after.get("name", "")} ({after.get("nccAdgroupId", "")})'
    if after.get(key) != expected:
        print(f'[확인 실패] {label}: {key} 기대 {expected}, 실제 {after.get(key)}')
        return 1
    extra = other_changes(before, after, key)
    if extra:
        print(f'[주의] {label}: {key} 외에 바뀐 값이 있습니다: {", ".join(sorted(extra))}')
        return 1
    print(f'[반영 완료] {label}: {key}만 변경됨')
    return 0


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
    r = sub.add_parser('rename', help='광고그룹 이름만 변경 (기본 미리보기)')
    r.add_argument('--id', required=True, help='광고그룹ID 1개')
    r.add_argument('--name', required=True, help='새 광고그룹 이름')
    r.add_argument('--apply', action='store_true', help='실제 반영 (없으면 미리보기)')
    for cmd, what in (('media', '매체'), ('schedule', '요일·시간대')):
        t = sub.add_parser(cmd, help=f'{what} 타게팅만 변경 (기본 미리보기)')
        t.add_argument('--ids', required=True, help='광고그룹ID, 쉼표 구분')
        t.add_argument('--target', required=True, help='새 타게팅 JSON (list 결과 형식 그대로)')
        t.add_argument('--apply', action='store_true', help='실제 반영 (없으면 미리보기)')
    d = sub.add_parser('delete-ads', help='소재 삭제 (기본 미리보기, 복구 불가)')
    d.add_argument('--ad-ids', required=True, help='소재ID, 쉼표 구분')
    d.add_argument('--customer', help='계정ID (기본: NAVER_CUSTOMER_IDS 첫 번째)')
    d.add_argument('--apply', action='store_true', help='실제 삭제 (없으면 미리보기)')
    args = p.parse_args()
    client = Client()
    return {'list': cmd_list, 'rename': cmd_rename, 'media': cmd_target,
            'schedule': cmd_target, 'delete-ads': cmd_delete_ads}[args.cmd](client, args)


if __name__ == '__main__':
    try:
        sys.exit(main())
    except ValueError as e:
        print(f'오류: {e}', file=sys.stderr)
        sys.exit(2)
