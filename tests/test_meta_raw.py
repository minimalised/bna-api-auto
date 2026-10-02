import sys
import types
import unittest
from unittest.mock import patch
try:
    import requests
except ImportError:
    sys.modules['requests'] = types.ModuleType('requests')
import meta_report as m

class MetaTest(unittest.TestCase):
    def test_ad_grain_and_purchase_only(self):
        raw={'date_start':'2026-10-01','account_id':'1','account_name':'a','account_currency':'KRW','campaign_id':'2','campaign_name':'c','adset_id':'3','adset_name':'g','ad_id':'4','ad_name':'소재 A','impressions':'10','inline_link_clicks':'2','spend':'123.45','actions':[{'action_type':m.PURCHASE_VALUE_TYPE,'value':'1.5'},{'action_type':'lead','value':'9'}],'action_values':[{'action_type':m.PURCHASE_VALUE_TYPE,'value':'300.25'}]}
        r=m.build_row(raw,'ad')
        self.assertEqual(r['전환수'],1.5)
        self.assertEqual(r['비용'],123.45)
        self.assertEqual(r['광고명'],'소재 A')
        self.assertEqual(set(r),set(m.DIMS+m.AD_DIMS+m.METRICS))
        with patch.object(m,'api_get',return_value={'data':[raw]}) as api:
            m.fetch_insights('act_1','fake','2026-10-01','2026-10-01','ad')
            p=api.call_args.args[1]
            self.assertEqual(p['level'],'ad')
            self.assertIn('ad_id',p['fields'])
            self.assertNotIn('reach',p['fields'])
