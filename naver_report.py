#!/usr/bin/env python3
"""Naver Search Ads → summary, campaign, search, media RAW tabs. See README.md for API coverage limits.
No credentials at import time. Python 3.10+, gspread 6.x for sheet writes.
"""
import argparse
import base64
import csv
import gzip
import hashlib
import hmac
import io
import json
import os
import sys
import time
import urllib.error
import urllib.parse
import urllib.request
import zipfile
from datetime import date, datetime, timedelta, timezone
from decimal import Decimal, InvalidOperation
from pathlib import Path

KST = timezone(timedelta(hours=9))
BASE_URL = 'https://api.searchad.naver.com'
REPORTS = ('campaign', 'search', 'media')
DIMS = {
    'campaign': ['날짜', '광고상품', '캠페인명'],
    'search': ['날짜', '광고상품', '캠페인명', '광고그룹명', '검색어'],
    'media': ['날짜', '광고상품', '캠페인명', '광고그룹명', 'PC/모바일 매체', '검색/콘텐츠 매체'],
}
METRICS = ['노출수', '클릭수', '비용', '전환수', '전환매출액']
META = ['계정ID', '캠페인ID', '광고그룹ID', '데이터출처', '비고', '수집시각']
FIELDS = ['impCnt', 'clkCnt', 'salesAmt', 'purchaseCcnt', 'purchaseConvAmt']
TYPES = {'WEB_SITE': '파워링크', 'SHOPPING': '쇼핑검색', 'BRAND_SEARCH': '브랜드검색',
         'POWER_CONTENTS': '파워컨텐츠', 'PLACE': '플레이스'}
# Official positional TSV schemas. A changed column count is a hard error.
SCHEMAS = {
    'AD': 'day customer campaign group keyword ad biz media device imp click cost rank view'.split(),
    'AD_CONVERSION': 'day customer campaign group keyword ad biz media device method conv_type conv revenue'.split(),
    'EXPKEYWORD': 'day customer campaign group query media device query_type imp click cost view'.split(),
    'SHOPPINGKEYWORD_DETAIL': 'day customer campaign group query ad biz hour region media device imp click cost rank view'.split(),
    'SHOPPINGKEYWORD_CONVERSION_DETAIL': 'day customer campaign group query ad biz hour region media device method conv_type conv revenue'.split(),
}


def env(name, default=None):
    value = os.environ.get(name, '').strip()
    if value:
        return value
    if default is not None:
        return default
    raise ValueError(f'환경변수 {name}가 필요합니다.')


def number(v):
    try:
        n = Decimal(str(v).replace(',', ''))
    except (InvalidOperation, ValueError):
        raise ValueError('숫자 필드 누락 또는 잘못된 숫자') from None
    if not n.is_finite():
        raise ValueError('유한하지 않은 숫자')
    return int(n) if n == n.to_integral_value() else float(n)


def days(since, until):
    d = date.fromisoformat(since)
    while d <= date.fromisoformat(until):
        yield d.isoformat()
        d += timedelta(days=1)


def normalize_day(value):
    s = str(value).strip()
    if len(s) == 8 and s.isdigit():
        return datetime.strptime(s, '%Y%m%d').date().isoformat()
    return date.fromisoformat(s[:10]).isoformat()


def table_bytes(content):
    if content.startswith(b'\x1f\x8b'):
        content = gzip.decompress(content)
    elif content.startswith(b'PK\x03\x04'):
        with zipfile.ZipFile(io.BytesIO(content)) as z:
            files = [n for n in z.namelist() if not n.endswith('/')]
            if len(files) != 1:
                raise ValueError('보고서 ZIP은 데이터 파일 1개여야 합니다.')
            content = z.read(files[0])
    try:
        return content.decode('utf-8-sig')
    except UnicodeDecodeError:
        return content.decode('cp949')


def parse_report(content, report, customer, day):
    schema = SCHEMAS[report]
    text = table_bytes(content)
    if text.lstrip().startswith(('<', '{', '[')):
        raise ValueError('보고서 다운로드가 TSV가 아닙니다.')
    rows = []
    for line, cells in enumerate(csv.reader(io.StringIO(text), delimiter='\t'), 1):
        if not cells or all(v == '' for v in cells):
            continue
        if len(cells) != len(schema):
            raise ValueError(f'{report} {line}행: 열 수 {len(cells)}, 예상 {len(schema)}. 스키마 확인 필요')
        r = dict(zip(schema, cells))
        if normalize_day(r['day']) != day or r['customer'] != str(customer):
            raise ValueError(f'{report}: 요청한 계정/날짜와 응답 불일치')
        for k in ('imp', 'click', 'cost', 'rank', 'conv', 'revenue'):
            if k in r:
                r[k] = number(r[k])
        rows.append(r)
    return rows


class Client:
    def __init__(self):
        self.key = env('NAVER_API_KEY')
        self.secret = env('NAVER_SECRET_KEY')
        self.poll_timeout = int(env('NAVER_REPORT_TIMEOUT', '600'))

    def headers(self, method, path, customer):
        ts = str(int(time.time() * 1000))
        sig = base64.b64encode(hmac.new(self.secret.encode(),
                    f'{ts}.{method}.{path}'.encode(), hashlib.sha256).digest()).decode()
        return {'Content-Type': 'application/json; charset=UTF-8', 'X-Timestamp': ts,
                'X-API-KEY': self.key, 'X-Customer': str(customer), 'X-Signature': sig}

    def request(self, method, path, customer, params=None, body=None, raw_url=None):
        url = raw_url or BASE_URL + path
        if params:
            url += '?' + urllib.parse.urlencode(params)
        data = json.dumps(body).encode() if body is not None else None
        # Never print signed download URLs, headers, or server response bodies.
        for attempt in range(5):
            req = urllib.request.Request(url, data=data, method=method,
                    headers=self.headers(method, path, customer))
            try:
                with urllib.request.urlopen(req, timeout=60) as response:
                    content = response.read()
                return content if raw_url else json.loads(content)
            except urllib.error.HTTPError as e:
                status = e.code
                code = ''
                try:
                    code = str(json.loads(e.read()).get('code', ''))
                except (ValueError, AttributeError):
                    pass
                if status != 429 and status < 500:
                    raise RuntimeError(f'{method} {path}: HTTP {status}, API code {code}') from None
                reason = f'HTTP {status}'
            except (urllib.error.URLError, TimeoutError, ConnectionError):
                reason = 'network/timeout'
            if attempt == 4:
                raise RuntimeError(f'{method} {path}: 재시도 초과 ({reason})')
            time.sleep(min(2 ** (attempt + 1), 20))

    def get(self, path, customer, params=None):
        return self.request('GET', path, customer, params=params)

    def download(self, url, customer):
        u = urllib.parse.urlsplit(url)
        if u.scheme != 'https' or u.hostname not in ('api.searchad.naver.com', 'api.naver.com') or u.path != '/report-download':
            raise ValueError('예상하지 못한 보고서 다운로드 주소: 공식 스펙 확인 필요')
        # Keep returned URL including fileVersion, sign only pathname.
        return self.request('GET', u.path, customer, raw_url=url)

    def job(self, customer, report=None, day=None, item=None):
        master = item is not None
        path = '/master-reports' if master else '/stat-reports'
        payload = {'item': item} if master else {'reportTp': report, 'statDt': day.replace('-', '')}
        for generation in range(2):
            job = self.request('POST', path, customer, body=payload)
            job_id = job.get('id' if master else 'reportJobId')
            if job_id is None:
                raise ValueError('보고서 작업 ID 누락')
            deadline = time.monotonic() + self.poll_timeout
            while True:
                status = str(job.get('status', '')).upper()
                if status == 'BUILT':
                    if not job.get('downloadUrl'):
                        raise ValueError('BUILT 보고서에 다운로드 URL 누락')
                    return self.download(job['downloadUrl'], customer)
                if status == 'NONE':
                    return b''
                if status == 'CHANGED':
                    break
                if status == 'ERROR':
                    raise RuntimeError('보고서 생성 ERROR')
                if status not in ('REGIST', 'RUNNING', 'WAITING', 'AGGREGATING'):
                    raise RuntimeError(f'알 수 없는 보고서 상태: {status}')
                if time.monotonic() >= deadline:
                    raise TimeoutError('보고서 생성 제한시간 초과')
                time.sleep(5)
                job = self.get(f'{path}/{job_id}', customer)
        raise RuntimeError('보고서 데이터 변경으로 재생성 필요')


def stats_data(response):
    if not isinstance(response, dict):
        raise ValueError('stats 응답 형식 오류')
    for key in ('summaryStatResponse', 'dailyStatResponse'):
        if key in response:
            response = response[key]
            break
    if not isinstance(response, dict) or not isinstance(response.get('data'), list):
        raise ValueError('stats data 배열 누락')
    return response['data']


def metric_values(s):
    # Missing purchase metrics must NEVER fall back to total conversions or zero.
    v = [number(s[f]) for f in FIELDS[:5]]
    return dict(zip(METRICS, v))


class Collector:
    def __init__(self, client, customer):
        self.client, self.customer = client, str(customer)
        self.campaigns = {}
        self.groups = {}
        self.media = None
        self.cache = {}
        self.group_errors = {}
        camps = client.get('/ncc/campaigns', customer)
        if not isinstance(camps, list):
            raise ValueError('캠페인 목록 형식 오류')
        self.campaigns = {c['nccCampaignId']: c for c in camps}

    def load_groups(self):
        for cid in self.campaigns:
            try:
                cursor = None
                while True:
                    p = {'nccCampaignId': cid, 'recordSize': 1000, 'selector': 'NEXT'}
                    if cursor:
                        p['baseSearchId'] = cursor
                    part = self.client.get('/ncc/adgroups', self.customer, p)
                    if not isinstance(part, list):
                        raise ValueError('광고그룹 목록 형식 오류')
                    for g in part:
                        self.groups[g['nccAdgroupId']] = g
                    if len(part) < 1000:
                        break
                    next_cursor = part[-1]['nccAdgroupId']
                    if next_cursor == cursor:
                        raise ValueError('광고그룹 페이지 이동 실패')
                    cursor = next_cursor
            except Exception as e:
                self.group_errors[cid] = str(e)

    def base(self, day, cid, gid='', source=''):
        c = self.campaigns.get(cid, {})
        g = self.groups.get(gid, {})
        tp = c.get('campaignTp', '')
        notes = []
        if not c:
            notes.append('캠페인 메타정보 없음(ID 유지)')
        if gid and not g:
            notes.append('광고그룹 메타정보 없음(ID 유지)')
        return {'날짜': day, '광고상품': TYPES.get(tp, tp or '미확인'),
                '캠페인명': c.get('name', cid), '광고그룹명': g.get('name', gid),
                '계정ID': self.customer, '캠페인ID': cid, '광고그룹ID': gid,
                '데이터출처': source, '비고': '; '.join(notes),
                '수집시각': datetime.now(KST).isoformat(timespec='seconds')}

    def stat(self, entity, day, breakdown=None):
        p = {'id': entity, 'fields': json.dumps(FIELDS),
             'timeRange': json.dumps({'since': day, 'until': day}), 'timeIncrement': 'allDays'}
        if breakdown:
            p['breakdown'] = breakdown
        return stats_data(self.client.get('/stats', self.customer, p))

    def campaign(self, day):
        out = []
        for cid in self.campaigns:
            entries = self.stat(cid, day)
            if len(entries) > 1:
                raise ValueError('캠페인 일자 요약이 여러 행으로 반환됨')
            for s in entries:
                if s.get('id', cid) != cid:
                    raise ValueError('캠페인 stats ID 불일치')
                r = self.base(day, cid, source='stats')
                r.update(metric_values(s))
                out.append(r)
        return out

    def bulk(self, report, day):
        key = report, day
        if key not in self.cache:
            content = self.client.job(self.customer, report=report, day=day)
            self.cache[key] = parse_report(content, report, self.customer, day)
        return self.cache[key]

    def load_media(self):
        if self.media is not None:
            return
        raw = self.client.job(self.customer, item='Media')
        media = {}
        for n, c in enumerate(csv.reader(io.StringIO(table_bytes(raw)), delimiter='\t'), 1):
            if not c or all(v == '' for v in c):
                continue
            if len(c) != 13:
                raise ValueError(f'Media 마스터 {n}행: 스키마 불일치')
            if c[0].lower() != 'media':
                continue
            def boolean(value):
                if value.lower() not in ('true', 'false', '1', '0'):
                    raise ValueError('매체 마스터 boolean 형식 오류')
                return value.lower() in ('true', '1')
            search, content = boolean(c[8]), boolean(c[9])
            if search == content:
                media[c[1]] = '분류미확인:' + c[1]
            else:
                media[c[1]] = '검색' if search else '콘텐츠'
        if not media:
            raise ValueError('Media 마스터 비어 있음')
        self.media = media

    def media_report(self, day):
        self.load_media()
        perf = self.bulk('AD', day)
        conv = self.bulk('AD_CONVERSION', day)
        def key(r):
            dev = r['device']
            if dev.upper() == 'PC':
                dev = 'PC'
            elif dev.upper() in ('MOBILE', 'MOBILE_APP', 'MOB'):
                dev = '모바일'
            # Undocumented values are kept, never guessed as PC/Mobile.
            classification = self.media.get(r['media'], '분류미확인:' + r['media'])
            return r['campaign'], r['group'], dev, classification
        return self.aggregate(day, perf, conv, key, ['PC/모바일 매체', '검색/콘텐츠 매체'],
                              'AD+AD_CONVERSION+Media', purchase=True, rank=False)

    def search(self, day):
        # Separate source streams: never fabricate Powerlink conversions from registered keywords.
        key = lambda r: (r['campaign'], r['group'], r['query'])
        power = self.aggregate(day, self.bulk('EXPKEYWORD', day), [], key, ['검색어'],
                               'EXPKEYWORD', purchase=False, rank=False)
        shop = self.aggregate(day, self.bulk('SHOPPINGKEYWORD_DETAIL', day),
                              self.bulk('SHOPPINGKEYWORD_CONVERSION_DETAIL', day), key, ['검색어'],
                              'SHOPPINGKEYWORD_DETAIL+SHOPPINGKEYWORD_CONVERSION_DETAIL', purchase=True, rank=False)
        for r in power:
            r['비고'] = (r['비고'] + '; 파워링크 검색어: 전환수·매출액 API 미제공').strip('; ')
        for r in shop:
            r['비고'] = (r['비고'] + '; 검색어가 있는 검색 지면만 집계').strip('; ')
        return power + shop

    def aggregate(self, day, perf, conv, keyfn, labels, source, purchase, rank):
        totals = {}
        def bucket(s):
            k = keyfn(s)
            if k not in totals:
                totals[k] = {'imp': 0, 'click': 0, 'cost': Decimal(0), 'rank': 0, 'conv': 0, 'revenue': Decimal(0)}
            return totals[k]
        for s in perf:
            b = bucket(s)
            for f in ('imp', 'click', 'rank'):
                b[f] += s.get(f, 0)
            b['cost'] += Decimal(str(s['cost']))
        for s in conv:
            if s['conv_type'] != 'purchase':
                continue
            b = bucket(s)
            b['conv'] += s['conv']
            b['revenue'] += Decimal(str(s['revenue']))
        out = []
        for k, b in totals.items():
            r = self.base(day, k[0], k[1], source)
            r.update(zip(labels, k[2:]))
            r.update({'노출수': b['imp'], '클릭수': b['click'], '비용': number(b['cost']),
                      '전환수': b['conv'] if purchase else '',
                      '전환매출액': number(b['revenue']) if purchase else ''})
            if any(str(v).startswith('분류미확인:') for v in k):
                r['비고'] += '; 매체 분류 확인 필요'
            out.append(r)
        return out


def header(report):
    return DIMS[report] + METRICS + META


def row_key(r, report):
    extras = DIMS[report][4:] if report != 'campaign' else []
    return tuple(str(r.get(c, '')) for c in ['계정ID', '날짜', '캠페인ID', '광고그룹ID'] + extras)


def merge_rows(old, new, scopes, report):
    # Scope = account/day; campaign reports additionally scope to queried entities.
    # Commit only after ALL required calls for that report/day succeed.
    def covered(r):
        key = tuple(str(r.get(c, '')) for c in ['계정ID', '날짜', '캠페인ID', '광고그룹ID'])
        return any(key[:length] in scopes for length in (2, 3, 4))
    kept = [r for r in old if not covered(r)]
    out = kept + new
    seen = set()
    for r in out:
        k = row_key(r, report)
        if k in seen:
            raise ValueError(f'{report}: 중복 키 발견. 쓰기 중단')
        seen.add(k)
    return sorted(out, key=lambda r: (str(r['날짜']), str(r['계정ID']), str(r['캠페인ID']), str(r.get('광고그룹ID', ''))), reverse=True)


class SheetWriter:
    def write(self, report, rows, scopes, outdir):
        from raw_store import save
        save('naver_' + report + '_daily_v2', header(report), rows,
             {(str(x[0]), str(x[1])) for x in scopes},
             ['계정ID', '날짜', '캠페인ID', '광고그룹ID'] + (DIMS[report][4:] if report != 'campaign' else []),
             False, outdir)


def colname(n):
    result = ''
    while n:
        n, remainder = divmod(n - 1, 26)
        result = chr(65 + remainder) + result
    return result


def write_csv(path, fields, rows):
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open('w', encoding='utf-8-sig', newline='') as f:
        w = csv.DictWriter(f, fieldnames=fields, extrasaction='ignore')
        w.writeheader()
        w.writerows(rows)


def main():
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument('--since')
    p.add_argument('--until')
    p.add_argument('--lookback-days', type=int, default=1)
    p.add_argument('--reports', default=','.join(REPORTS))
    p.add_argument('--dry-run', action='store_true', help='API 수집+CSV 생성만, 시트 변경 없음')
    p.add_argument('--list-accounts', action='store_true')
    args = p.parse_args()
    today = datetime.now(KST).date()
    if args.lookback_days < 1:
        p.error('--lookback-days must be >= 1')
    since = args.since or (today - timedelta(days=args.lookback_days)).isoformat()
    until = args.until or (args.since if args.since else (today - timedelta(days=1)).isoformat())
    since, until = normalize_day(since), normalize_day(until)
    if since > until or date.fromisoformat(until) >= today:
        p.error('시작일 ≤ 종료일 < 오늘(KST)이어야 합니다.')
    if since < '2026-03-30':
        p.error('이 버전은 VAT 기준 통일을 위해 2026-03-30 이후만 지원합니다.')
    selected = list(dict.fromkeys(x.strip() for x in args.reports.split(',') if x.strip()))
    if not selected or set(selected) - set(REPORTS):
        p.error('--reports: campaign,search,media 중 선택')
    owner = env('NAVER_CUSTOMER_ID')
    customers = list(dict.fromkeys(c.strip() for c in env('NAVER_CUSTOMER_IDS', owner).split(',') if c.strip()))
    client = Client()
    if args.list_accounts:
        for customer in customers:
            c = Collector(client, customer)
            print(f'{customer}: 캠페인 {len(c.campaigns)}개')
        return 0
    runid = datetime.now(KST).strftime('%Y%m%dT%H%M%S')
    outdir = Path('reports') / f'naver_raw_v2_{runid}'
    outdir.mkdir(parents=True, exist_ok=True)
    result = {r: [] for r in selected}
    scopes = {r: set() for r in selected}
    status = []
    errors = []
    print('범위: 캠페인·검색어·매체 RAW. 구매만 집계하며 미제공 지표는 빈칸.', flush=True)
    for customer in customers:
        try:
            collector = Collector(client, customer)
            if set(selected) - {'campaign'}:
                collector.load_groups()
        except Exception as e:
            errors.append(f'{customer}: 메타데이터 조회 실패 {e}')
            continue
        for day in days(since, until):
            for report in selected:
                try:
                    method = {'campaign': collector.campaign, 'search': collector.search,
                              'media': collector.media_report}.get(report)
                    rows = method(day)
                    # Validate keys before treating a day as replaceable.
                    merge_rows([], rows, set(), report)
                    result[report].extend(rows)
                    if report == 'campaign':
                        scopes[report].update((customer, day, cid) for cid in collector.campaigns)
                    else:
                        scopes[report].add((customer, day))
                    status.append({'계정ID': customer, '날짜': day, '보고서': report,
                                   '상태': '수집성공', '행수': len(rows), '설명': '문서의 지원 범위 내 수집'})
                    print(f'{customer} {day} {report}: {len(rows)}행', flush=True)
                except Exception as e:
                    msg = f'{customer} {day} {report}: {e}'
                    errors.append(msg)
                    status.append({'계정ID': customer, '날짜': day, '보고서': report,
                                   '상태': '실패_기존보존', '행수': 0, '설명': str(e)})
                    print(msg, file=sys.stderr, flush=True)
            collector.cache.clear()
    for report in selected:
        write_csv(outdir / f'{report}.csv', header(report), result[report])
    write_csv(outdir / 'collection_status.csv', ['계정ID', '날짜', '보고서', '상태', '행수', '설명'], status)
    if not args.dry_run:
        try:
            writer = SheetWriter()
            for report in selected:
                if scopes[report]:
                    try:
                        writer.write(report, result[report], scopes[report], outdir)
                    except Exception as e:
                        errors.append(f'{report}: 시트 쓰기 실패 ({type(e).__name__}): 헤더/권한/용량 확인')
        except Exception as e:
            errors.append(f'시트 연결 실패 ({type(e).__name__}): 인증/권한 확인')
    if 'campaign' in selected:
        from raw_store import summary as make_summary, save, SUMMARY_HEADER, SUMMARY_DIMS
        normalized = [dict(r, 매체='naver', 계정명='', 통화='KRW', 전환기준='구매', 클릭기준='클릭')
                      for r in result['campaign']]
        try:
            save('naver_summary_daily_v2', SUMMARY_HEADER, make_summary(normalized),
                 {(str(x[0]), str(x[1])) for x in scopes['campaign']},
                 SUMMARY_DIMS, args.dry_run, outdir)
        except Exception as e:
            errors.append(f'summary 저장 실패: {type(e).__name__}: {e}')
    summary = ['### 네이버 RAW 수집', f'기간: {since} ~ {until}',
               '검색어: 파워링크·쇼핑검색만. 성별·연령은 수집하지 않음.',
               '파워링크 검색어 전환수/매출는 미제공(빈칸).',
               '| RAW | 성공 계정·날짜 | 행수 |', '|---|---:|---:|']
    summary += [f'| {r} | {len({s[:2] for s in scopes[r]})} | {len(result[r])} |' for r in selected]
    summary += [f'오류 {len(errors)}건. 상세: collection_status.csv',
                '성공 수집 수는 API 수집 기준이며, 시트 쓰기 실패는 아래 오류에 별도 표시됩니다.']
    summary += ['- ' + e for e in errors]
    text = '\n'.join(summary) + '\n'
    (outdir / 'summary.md').write_text(text, encoding='utf-8')
    (outdir / 'errors.json').write_text(json.dumps(errors, ensure_ascii=False, indent=2), encoding='utf-8')
    if os.environ.get('GITHUB_STEP_SUMMARY'):
        with open(os.environ['GITHUB_STEP_SUMMARY'], 'a', encoding='utf-8') as f:
            f.write(text)
    print(f'결과 저장: {outdir}', flush=True)
    return 1 if errors else 0


if __name__ == '__main__':
    try:
        sys.exit(main())
    except (ValueError, RuntimeError, KeyError) as exc:
        print(f'실행 중단: {exc}', file=sys.stderr)
        sys.exit(1)
