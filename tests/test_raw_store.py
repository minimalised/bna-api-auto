import unittest
from tempfile import TemporaryDirectory
from pathlib import Path
from unittest.mock import patch
import raw_store as r
import naver_report as n


def row(account='a', day='2026-10-01', campaign='c', cost=10):
    return dict(zip(r.SUMMARY_DIMS,[day,'naver',account,'','쇼핑검색','KRW','구매','클릭']),
                캠페인ID=campaign,노출수=10,클릭수=2,비용=cost,전환수=1.5,전환매출액=20)


class RawTest(unittest.TestCase):
    def test_idempotent_and_failed_scope_preserved(self):
        old=[row(),row('b'),row(day='2026-09-30')]
        new=[row(cost=99)]
        keys=['계정ID','날짜','캠페인ID']
        first=r.merge(old,new,{('a','2026-10-01')},keys)
        self.assertEqual(first,r.merge(first,new,{('a','2026-10-01')},keys))
        self.assertEqual(len(first),3)
        self.assertEqual(sum(x['비용'] for x in first),119)
        self.assertEqual(len(r.merge(first,[],{('a','2026-10-01')},keys)),2)

    def test_duplicate_rejected(self):
        with self.assertRaises(ValueError):
            r.merge([],[row(),row()],set(),['계정ID','날짜','캠페인ID'])

    def test_summary_adds_only_campaign_metrics_and_preserves_unknown(self):
        a=row();b=row(campaign='d',cost=30)
        total=r.summary([a,b])[0]
        self.assertEqual(total['비용'],40)
        self.assertEqual(total['전환수'],3)
        self.assertEqual(set(total),set(r.SUMMARY_HEADER))
        b['전환수']=''
        self.assertEqual(r.summary([a,b])[0]['전환수'],'')

    def test_dry_run_exports_no_sheet_access(self):
        with TemporaryDirectory() as d, patch.dict('os.environ',{'SHEET_ID':'fake'}):
            r.save('test',r.SUMMARY_HEADER,r.summary([row()]),{('a','2026-10-01')},r.SUMMARY_DIMS,True,Path(d))
            self.assertTrue((Path(d)/'test.csv').exists())

    def test_naver_has_no_demographic_or_calculated_columns(self):
        self.assertEqual(n.REPORTS,('campaign','search','media'))
        self.assertEqual(n.METRICS,r.METRICS)
        self.assertNotIn('avgRnk',n.FIELDS)
        c=n.Collector.__new__(n.Collector)
        c.base=lambda *a,**k: {}
        base={'campaign':'c','group':'g','query':'q','imp':10,'click':2,'cost':20,'rank':30}
        rows=c.aggregate('2026-10-01',[base],[],lambda x:(x['campaign'],x['group'],x['query']),['검색어'],'EXPKEYWORD',False,False)
        self.assertEqual(rows[0]['전환수'],'')
        self.assertNotIn('평균노출순위',rows[0])

if __name__=='__main__': unittest.main()
