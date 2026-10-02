import unittest
from tempfile import TemporaryDirectory
from pathlib import Path
from unittest.mock import patch
import raw_store as r
import naver_report as n


def row(account='a', day='2026-10-01', campaign='c', cost=10):
    return dict(zip(r.SUMMARY_DIMS,[day,'naver',account,'','���ΰ˻�','KRW','����','Ŭ��']),
                ķ����ID=campaign,�����=10,Ŭ����=2,���=cost,��ȯ��=1.5,��ȯ�����=20)


class RawTest(unittest.TestCase):
    def test_idempotent_and_failed_scope_preserved(self):
        old=[row(),row('b'),row(day='2026-09-30')]
        new=[row(cost=99)]
        keys=['����ID','��¥','ķ����ID']
        first=r.merge(old,new,{('a','2026-10-01')},keys)
        self.assertEqual(first,r.merge(first,new,{('a','2026-10-01')},keys))
        self.assertEqual(len(first),3)
        self.assertEqual(sum(x['���'] for x in first),119)
        self.assertEqual(len(r.merge(first,[],{('a','2026-10-01')},keys)),2)

    def test_duplicate_rejected(self):
        with self.assertRaises(ValueError):
            r.merge([],[row(),row()],set(),['����ID','��¥','ķ����ID'])

    def test_summary_adds_only_campaign_metrics_and_preserves_unknown(self):
        a=row();b=row(campaign='d',cost=30)
        total=r.summary([a,b])[0]
        self.assertEqual(total['���'],40)
        self.assertEqual(total['��ȯ��'],3)
        self.assertEqual(set(total),set(r.SUMMARY_HEADER))
        b['��ȯ��']=''
        self.assertEqual(r.summary([a,b])[0]['��ȯ��'],'')

    def test_dry_run_exports_no_sheet_access(self):
        with TemporaryDirectory() as d, patch.dict('os.environ',{'SHEET_ID':'fake'}):
            r.save('test',r.SUMMARY_HEADER,r.summary([row()]),{('a','2026-10-01')},r.SUMMARY_DIMS,True,Path(d))
            self.assertTrue((Path(d)/'test.csv').exists())

    def test_naver_writer_exports_only_report_columns(self):
        collector = n.Collector.__new__(n.Collector)
        collector.customer = 'a'
        collector.campaigns = {'c': {'name': 'Campaign', 'campaignTp': 'WEB_SITE'}}
        collector.groups = {'g': {'name': 'Group'}}
        for report in n.REPORTS:
            with self.subTest(report=report), TemporaryDirectory() as d, patch.dict('os.environ', {'SHEET_ID': ''}):
                data = collector.base('2026-10-01', 'c', '' if report == 'campaign' else 'g', 'stats')
                data.update(dict.fromkeys(n.METRICS, 1))
                data.update({field: 'test' for field in n.DIMS[report][4:]})
                n.SheetWriter().write(report, [data], {('a', '2026-10-01')}, Path(d))
                import csv
                with (Path(d) / ('naver_' + report + '_daily_v2.csv')).open(encoding='utf-8-sig', newline='') as f:
                    exported = list(csv.DictReader(f))
                self.assertEqual(list(exported[0]), n.header(report))
                self.assertEqual(exported[0]['ķ���θ�'], 'Campaign')
                self.assertEqual(exported[0]['��ȯ��'], '1')
                if report == 'campaign':
                    self.assertNotIn('�����׷��', exported[0])

    def test_naver_has_no_demographic_or_calculated_columns(self):
        self.assertEqual(n.REPORTS,('campaign','search','media'))
        self.assertEqual(n.METRICS,r.METRICS)
        self.assertNotIn('avgRnk',n.FIELDS)
        c=n.Collector.__new__(n.Collector)
        c.base=lambda *a,**k: {}
        base={'campaign':'c','group':'g','query':'q','imp':10,'click':2,'cost':20,'rank':30}
        rows=c.aggregate('2026-10-01',[base],[],lambda x:(x['campaign'],x['group'],x['query']),['�˻���'],'EXPKEYWORD',False,False)
        self.assertEqual(rows[0]['��ȯ��'],'')
        self.assertNotIn('��ճ������',rows[0])

if __name__=='__main__': unittest.main()

