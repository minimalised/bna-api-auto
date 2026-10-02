import unittest
from types import SimpleNamespace as N
from google_purchase import merge_campaigns, resolve_action, fetch_purchase, PURCHASE_ACTION_NAME

ACTION = N(resource_name='customers/9/conversionActions/7', name=PURCHASE_ACTION_NAME,
           status=N(name='ENABLED'))


def row(cid=1, spend=100, purchases=1.25, value=300.5):
    return N(customer=N(id=2, descriptive_name='BNA', currency_code='KRW', time_zone='Asia/Seoul'),
             campaign=N(id=cid, name='campaign', advertising_channel_type=N(name='SEARCH')),
             segments=N(date='2026-09-30', conversion_action=ACTION.resource_name),
             metrics=N(impressions=100, clicks=10, cost_micros=spend*1000000,
                       conversions=purchases, conversions_value=value))


class Service:
    def __init__(self, responses):
        self.responses = iter(responses)
        self.calls = []

    def search_stream(self, **kwargs):
        self.calls.append(kwargs)
        response = next(self.responses)
        if isinstance(response, Exception):
            raise response
        return [N(results=response)]


def owner():
    return N(customer=N(conversion_tracking_setting=N(google_ads_conversion_customer='customers/9')))


class PurchaseTest(unittest.TestCase):
    def test_spend_once_and_fractional_purchase(self):
        result = merge_campaigns([row()], [row()], ACTION)[0]
        self.assertEqual(result['비용'], 100)
        self.assertEqual(result['전환수'], 1.25)
        self.assertEqual(result['전환매출액'], 300.5)

    def test_spend_only_and_purchase_only(self):
        result = merge_campaigns([row(1)], [row(2)], ACTION)
        self.assertEqual(result[0]['전환수'], 0)
        self.assertEqual(result[1]['전환수'], 1.25)
        self.assertEqual(result[1]['비용'], 0)

    def test_duplicate_fails(self):
        for performance, purchases in [([row(), row()], []), ([], [row(), row()])]:
            with self.assertRaises(ValueError):
                merge_campaigns(performance, purchases, ACTION)

    def test_wrong_action_fails(self):
        r = row()
        r.segments.conversion_action = 'customers/9/conversionActions/8'
        with self.assertRaises(ValueError):
            merge_campaigns([], [r], ACTION)

    def test_mcc_owner_and_exact_name(self):
        other = N(name='Google Channel Purchase extra')
        svc = Service([[owner()], [N(conversion_action=other), N(conversion_action=ACTION)]])
        self.assertEqual(resolve_action(svc, '2'), ACTION)
        self.assertEqual(svc.calls[1]['customer_id'], '9')

    def test_missing_or_ambiguous_action_fails(self):
        for actions in [[], [N(conversion_action=ACTION)]*2]:
            with self.assertRaises(ValueError):
                resolve_action(Service([[owner()], actions]), '2')

    def test_queries_separate_cost_and_conversion(self):
        svc = Service([[owner()], [N(conversion_action=ACTION)], [row()], [row()]])
        client = N(get_service=lambda _: svc)
        self.assertEqual(len(fetch_purchase(client, '2', '2026-09-30', '2026-09-30')), 1)
        self.assertNotIn('segments.conversion_action', svc.calls[2]['query'])
        self.assertNotIn('metrics.cost_micros', svc.calls[3]['query'])
        self.assertNotIn('impressions >', svc.calls[3]['query'])

    def test_failed_purchase_call_returns_no_partial_result(self):
        svc = Service([[owner()], [N(conversion_action=ACTION)], [row()], RuntimeError('API failed')])
        with self.assertRaises(RuntimeError):
            fetch_purchase(N(get_service=lambda _: svc), '2', '2026-09-30', '2026-09-30')

    def test_invalid_dates_before_api(self):
        with self.assertRaises(ValueError):
            fetch_purchase(None, '2', '2026-10-01', '2026-09-30')


if __name__ == '__main__':
    unittest.main()
