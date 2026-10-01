"""Purchase-only campaign reporting; no authentication or writes at import time."""
from datetime import date, datetime, timezone
import re

PURCHASE_ACTION_NAME = "Google Channel Purchase"
OWNER_QUERY = "SELECT customer.conversion_tracking_setting.google_ads_conversion_customer FROM customer"
ACTION_QUERY = """SELECT conversion_action.resource_name, conversion_action.name,
conversion_action.status FROM conversion_action"""
COMMON = """customer.id, customer.descriptive_name, customer.currency_code,
customer.time_zone, campaign.id, campaign.name, campaign.advertising_channel_type,
segments.date"""


def query_rows(service, customer_id, query):
    for batch in service.search_stream(customer_id=customer_id, query=query):
        yield from batch.results


def resolve_action(service, customer_id):
    settings = list(query_rows(service, customer_id, OWNER_QUERY))
    if len(settings) != 1:
        raise ValueError("전환 관리 계정을 확인할 수 없습니다.")
    owner = settings[0].customer.conversion_tracking_setting.google_ads_conversion_customer
    if not re.fullmatch(r"customers/[0-9]+", owner):
        raise ValueError("전환 관리 계정 ID가 올바르지 않습니다.")
    matches = [r.conversion_action for r in query_rows(service, owner.split('/')[1], ACTION_QUERY)
               if r.conversion_action.name == PURCHASE_ACTION_NAME]
    if len(matches) != 1:
        raise ValueError(f"{PURCHASE_ACTION_NAME}: 정확히 일치하는 액션이 {len(matches)}개입니다. 구매 0으로 처리하지 않습니다.")
    action = matches[0]
    if not re.fullmatch(r"customers/[0-9]+/conversionActions/[0-9]+", action.resource_name):
        raise ValueError("전환 액션 리소스 ID가 올바르지 않습니다.")
    return action


def identity(r):
    return (str(r.customer.id), r.segments.date, str(r.campaign.id))


def base_row(r, action, now):
    return {
        "날짜": r.segments.date, "계정ID": str(r.customer.id),
        "계정명": r.customer.descriptive_name, "캠페인ID": str(r.campaign.id),
        "캠페인명": r.campaign.name, "캠페인유형": r.campaign.advertising_channel_type.name,
        "통화": r.customer.currency_code, "계정시간대": r.customer.time_zone,
        "노출수": 0, "클릭수": 0, "광고비": 0.0,
        "구매수": 0.0, "구매매출": 0.0,
        "구매전환명": PURCHASE_ACTION_NAME, "구매전환리소스": action.resource_name,
        "구매전환상태": action.status.name,
        "전환지표기준": "metrics.conversions / metrics.conversions_value",
        "일자기준": "광고 상호작용일", "수집시각": now,
    }


def merge_campaigns(performance, purchases, action):
    """Full outer join at account/date/campaign; never duplicate campaign spend."""
    rows = {}
    now = datetime.now(timezone.utc).isoformat(timespec="seconds")
    for r in performance:
        key = identity(r)
        if key in rows:
            raise ValueError("캠페인 성과 중복 키")
        row = base_row(r, action, now)
        row.update({"노출수": r.metrics.impressions, "클릭수": r.metrics.clicks,
                    "광고비": r.metrics.cost_micros / 1_000_000})
        rows[key] = row
    seen = set()
    for r in purchases:
        key = identity(r)
        if r.segments.conversion_action != action.resource_name:
            raise ValueError("요청하지 않은 구매 액션 응답")
        if key in seen:
            raise ValueError("구매 성과 중복 키")
        seen.add(key)
        row = rows.setdefault(key, base_row(r, action, now))
        row["구매수"] = r.metrics.conversions
        row["구매매출"] = r.metrics.conversions_value
    for row in rows.values():
        cost, clicks, imps = row["광고비"], row["클릭수"], row["노출수"]
        purchase, value = row["구매수"], row["구매매출"]
        row.update({
            "CTR(%)": clicks / imps * 100 if imps else None,
            "CPC": cost / clicks if clicks else None,
            "ROAS(%)": value / cost * 100 if cost else None,
            "구매CPA": cost / purchase if purchase else None,
        })
    return [rows[k] for k in sorted(rows)]


def fetch_purchase(client, customer_id, since, until):
    # Validate before query interpolation, even for callers outside the CLI.
    since, until = date.fromisoformat(since).isoformat(), date.fromisoformat(until).isoformat()
    if since > until:
        raise ValueError("시작일은 종료일 이후일 수 없습니다.")
    service = client.get_service("GoogleAdsService")
    action = resolve_action(service, customer_id)
    scope = f"segments.date BETWEEN '{since}' AND '{until}'"
    performance_query = f"""SELECT {COMMON},
    metrics.impressions, metrics.clicks, metrics.cost_micros
    FROM campaign WHERE {scope}"""
    purchase_query = f"""SELECT {COMMON}, segments.conversion_action,
    metrics.conversions, metrics.conversions_value
    FROM campaign WHERE {scope}
    AND segments.conversion_action = '{action.resource_name}'"""
    # Materialize both complete responses before returning anything replaceable.
    performance = list(query_rows(service, customer_id, performance_query))
    purchases = list(query_rows(service, customer_id, purchase_query))
    return merge_campaigns(performance, purchases, action)
