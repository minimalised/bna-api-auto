"""Five additive metrics; independent report scopes and idempotent Sheets writes."""
import csv
import json
import os
from datetime import datetime, timedelta, timezone, date
from pathlib import Path
from decimal import Decimal

METRICS = ['노출수', '클릭수', '비용', '전환수', '전환매출액']
SUMMARY_DIMS = ['날짜', '매체', '계정ID', '계정명', '광고상품', '통화', '전환기준', '클릭기준']
SUMMARY_HEADER = SUMMARY_DIMS + METRICS
KST = timezone(timedelta(hours=9))


def period(since=None, until=None, lookback=1):
    today = datetime.now(KST).date()
    start = date.fromisoformat(since) if since else today - timedelta(days=lookback)
    end = date.fromisoformat(until) if until else (start if since else today - timedelta(days=1))
    if lookback < 1 or start > end or end >= today:
        raise ValueError('시작일 ≤ 종료일 < 오늘(KST), 조회 일수 ≥ 1이어야 합니다.')
    return start.isoformat(), end.isoformat()


def summary(rows):
    totals = {}
    for row in rows:
        key = tuple(str(row.get(k, '')) for k in SUMMARY_DIMS)
        if key not in totals:
            totals[key] = {m: Decimal(0) for m in METRICS}
        for m in METRICS:
            v = row[m]
            if v in ('', None):
                totals[key][m] = None
            elif totals[key][m] is not None:
                totals[key][m] += Decimal(str(v))
    return [dict(zip(SUMMARY_DIMS, key), **{m: '' if v is None else float(v)
             for m, v in values.items()}) for key, values in sorted(totals.items())]


def merge(old, new, scopes, keys):
    """Replace only successful account/day scopes; keep failed and historical days."""
    out = [r for r in old if (str(r['계정ID']), str(r['날짜'])) not in scopes] + new
    seen = set()
    for r in out:
        key = tuple(str(r.get(k, '')) for k in keys)
        if key in seen:
            raise ValueError('RAW 중복 키: 저장 중단')
        seen.add(key)
    return sorted(out, key=lambda r: tuple(str(r.get(k, '')) for k in keys))


def day_scopes(accounts, since, until):
    out = set()
    d = date.fromisoformat(since)
    while d.isoformat() <= until:
        out.update((str(a).removeprefix('act_'), d.isoformat()) for a in accounts)
        d += timedelta(days=1)
    return out


def csv_write(path, header, rows):
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open('w', encoding='utf-8-sig', newline='') as f:
        w = csv.DictWriter(f, fieldnames=header, extrasaction='raise')
        w.writeheader()
        w.writerows(rows)


ALIASES = {
    '일별': '날짜', '캠페인 유형': '광고상품', '캠페인유형': '광고상품',
    '캠페인': '캠페인명', '광고그룹': '광고그룹명',
    '총비용': '비용', '광고비': '비용', '링크클릭수': '클릭수',
    '구매완료 전환수': '전환수', '구매': '전환수',
    '구매완료 전환매출액': '전환매출액', '구매가치': '전환매출액', '전환가치': '전환매출액',
}


def existing_tab(tab):
    if tab == 'meta_campaign_daily_v2':
        return os.getenv('SHEET_TAB', '').strip() or 'meta_daily', True
    if tab == 'meta_ad_daily_v2':
        return os.getenv('META_AD_SHEET_TAB', '').strip() or 'meta_ad_daily', True
    if tab == 'google_campaign_daily_v2':
        return os.getenv('GOOGLE_SHEET_TAB', '').strip() or 'google_daily', True
    for report in ('campaign', 'search', 'media'):
        if tab == 'naver_' + report + '_daily_v2':
            return (os.getenv('NAVER_RAW_PREFIX', '').strip() or 'naver_raw') + '_' + report, True
    return tab.removesuffix('_daily_v2') + '_daily', False


def existing_layout(values, header, tab):
    original = values[0] if values else []
    canonical = [ALIASES.get(h, h) for h in original]
    if len(set(canonical)) != len(canonical) or any(not h for h in canonical):
        raise ValueError(f'{tab}: 중복/빈 컬럼명. 기존 탭 확인 필요')
    if values and not {'날짜', '계정ID'}.issubset(canonical):
        raise ValueError(f'{tab}: 날짜/계정ID 컬럼 누락')
    old = [dict(zip(canonical, v + [''] * (len(canonical)-len(v))))
           for v in values[1:] if any(v)]
    output_header = original + [h for h in header if h not in canonical]
    output_keys = canonical + [h for h in header if h not in canonical]
    return old, output_header, output_keys


def save(tab, header, rows, scopes, keys, dry_run, outdir):
    # Validate before exporting or opening a sheet; no legacy header union.
    merge([], rows, set(), keys)
    csv_write(outdir / (tab + '.csv'), header, rows)
    if '_summary_' in tab:
        return  # Summary is a CSV artifact only; the agreed sheet scope is six RAW reports.
    if dry_run or not os.getenv('SHEET_ID') or not scopes:
        return
    tab, required = existing_tab(tab)
    import gspread
    sh = gspread.service_account_from_dict(json.loads(os.environ['GCP_SA_KEY'])).open_by_key(os.environ['SHEET_ID'])
    try:
        ws = sh.worksheet(tab)
        values = ws.get_values(value_render_option='UNFORMATTED_VALUE')
        old, output_header, output_keys = existing_layout(values, header, tab)
    except gspread.WorksheetNotFound:
        if required:
            raise ValueError(f'{tab}: 기존 탭을 찾을 수 없습니다. 새 탭은 생성하지 않습니다.') from None
        print(f'{tab}: 기존 탭 없음, CSV만 저장')
        return
    merged = merge(old, rows, scopes, keys)
    if values:
        backup_rows = [dict(zip(values[0], v + [''] * (len(values[0])-len(v))))
                       for v in values[1:] if any(v)]
        csv_write(outdir / ('before_' + tab + '.csv'), values[0], backup_rows)
    grid = [output_header] + [[r.get(k, '') for k in output_keys] for r in merged]
    if ws.row_count < len(grid) or ws.col_count < len(output_header):
        ws.resize(rows=max(ws.row_count, len(grid)), cols=max(ws.col_count, len(output_header)))
    for i in range(0, len(grid), 2000):
        ws.update(range_name=f'A{i+1}', values=grid[i:i+2000], value_input_option='RAW')
    if len(old)+1 > len(grid):
        end = gspread.utils.rowcol_to_a1(len(old)+1, len(output_header))
        ws.batch_clear([f'A{len(grid)+1}:{end}'])
    ws.freeze(rows=1)
    print(f'{tab}: {len(rows)}행 수집 / 누적 {len(merged)}행')
