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


def save(tab, header, rows, scopes, keys, dry_run, outdir):
    # Validate before exporting or opening a sheet; no legacy header union.
    merge([], rows, set(), keys)
    csv_write(outdir / (tab + '.csv'), header, rows)
    if dry_run or not os.getenv('SHEET_ID') or not scopes:
        return
    import gspread
    sh = gspread.service_account_from_dict(json.loads(os.environ['GCP_SA_KEY'])).open_by_key(os.environ['SHEET_ID'])
    try:
        ws = sh.worksheet(tab)
        values = ws.get_values(value_render_option='UNFORMATTED_VALUE')
        if values and values[0] != header:
            raise ValueError(f'{tab}: 스키마 불일치. 기존 탭은 변경하지 않습니다.')
        old = [dict(zip(header, r + [''] * (len(header)-len(r)))) for r in values[1:] if any(r)]
    except gspread.WorksheetNotFound:
        ws, old = None, []
    merged = merge(old, rows, scopes, keys)
    if ws is not None:
        csv_write(outdir / ('before_' + tab + '.csv'), header, old)
    else:
        ws = sh.add_worksheet(title=tab, rows=max(100, len(merged)+1), cols=len(header))
    grid = [header] + [[r.get(k, '') for k in header] for r in merged]
    if ws.row_count < len(grid) or ws.col_count < len(header):
        ws.resize(rows=max(ws.row_count, len(grid)), cols=max(ws.col_count, len(header)))
    for i in range(0, len(grid), 2000):
        ws.update(range_name=f'A{i+1}', values=grid[i:i+2000], value_input_option='RAW')
    if len(old)+1 > len(grid):
        end = gspread.utils.rowcol_to_a1(len(old)+1, len(header))
        ws.batch_clear([f'A{len(grid)+1}:{end}'])
    ws.freeze(rows=1)
    print(f'{tab}: {len(rows)}행 수집 / 누적 {len(merged)}행')
