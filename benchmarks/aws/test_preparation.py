"""Offline checks for destructive boundaries, timeouts and budget rejection."""
from datetime import datetime, timezone
import json
from pathlib import Path
import sys
import subprocess
import tempfile
import unittest

from controller import collect_bucket
from guest import measure
from prepare import forecast
from watchdog import expired_instances


class FakePaginator:
    def __init__(self, pages):
        self.pages = pages
        self.arguments = None

    def paginate(self, **arguments):
        self.arguments = arguments
        return iter(self.pages)


class PreparationTests(unittest.TestCase):
    def test_watchdog_only_expires_owned_instances_and_checks_all_pages(self):
        def instance(identifier, expires, campaign='factumdb-test0000', managed='FactumDBBenchmark'):
            return {'InstanceId':identifier, 'Tags':[
                {'Key':'FactumDBCampaign','Value':campaign}, {'Key':'ManagedBy','Value':managed},
                {'Key':'ExpiresAt','Value':expires}]}
        paginator = FakePaginator([
            {'Reservations':[{'Instances':[instance('i-old','2026-10-10T00:00:00+00:00'),
                                          instance('i-future','2026-10-12T00:00:00+00:00')]}]},
            {'Reservations':[{'Instances':[instance('i-bad-expiry','invalid'),
                                          instance('i-other-campaign','invalid',campaign='other'),
                                          instance('i-unmanaged','invalid',managed='other')]}]}])
        class EC2:
            def get_paginator(self, name):
                return paginator
        ids = expired_instances(EC2(), 'factumdb-test0000', datetime(2026,10,11,tzinfo=timezone.utc))
        self.assertEqual(ids, ['i-old','i-bad-expiry'])
        self.assertIn({'Name':'tag:FactumDBCampaign','Values':['factumdb-test0000']}, paginator.arguments['Filters'])

    def test_budget_rejects_overrun_before_resources_are_created(self):
        config = {'matrix':[{'os':'windows','instance_type':'expensive'}], 'max_instance_minutes':90,
                  'scheduling_limit_usd':16, 'cleanup_reserve_usd':4}
        prices = {'prices':[{'instance':'expensive','os':'Windows',
                             'on_demand':[{'unit':'Hrs','usd':'100'}]}]}
        with self.assertRaisesRegex(ValueError, 'exceeds'):
            forecast(config, prices)

    def test_timeout_kills_subprocess_and_records_failure(self):
        with tempfile.TemporaryDirectory() as directory:
            result = measure([sys.executable,'-c','import time; time.sleep(60)'], Path(directory),
                             0.2, None, Path(directory), 'timeout')
            self.assertEqual(result['status'],'timeout')
            self.assertIsNotNone(result['exit_code'])
            self.assertLess(result['wall_seconds'],10)

    def test_failed_child_is_not_reported_as_pass(self):
        with tempfile.TemporaryDirectory() as directory:
            result = measure([sys.executable,'-c','raise SystemExit(7)'], Path(directory),
                             5, None, Path(directory), 'failure')
            self.assertEqual(result['status'],'failed')
            self.assertEqual(result['exit_code'],7)

    def test_download_failure_preserves_cloud_results(self):
        paginator = FakePaginator([{'Contents':[{'Key':'results/guest.zip'}]}])
        class S3:
            deleted = False
            def get_paginator(self, name):
                return paginator
            def download_file(self, *arguments):
                raise OSError('download interrupted')
            def delete_objects(self, **arguments):
                self.deleted = True
        client = S3()
        with tempfile.TemporaryDirectory() as directory, self.assertRaises(OSError):
            collect_bucket(client, 'owned-bucket', Path(directory))
        self.assertFalse(client.deleted)

    def test_result_keys_cannot_escape_local_destination(self):
        paginator = FakePaginator([{'Contents':[{'Key':'results/../../outside.txt'}]}])
        class S3:
            def get_paginator(self, name):
                return paginator
        with tempfile.TemporaryDirectory() as directory, self.assertRaises(ValueError):
            collect_bucket(S3(), 'owned-bucket', Path(directory))

    def test_current_campaign_stays_within_budget(self):
        root = Path(__file__).parent
        estimate = forecast(json.loads((root/'campaign.json').read_text()),
                            json.loads((root/'prices.json').read_text()))
        self.assertLess(float(estimate['forecast_usd']),16)

    def test_expired_guest_deadline_starts_no_workloads(self):
        with tempfile.TemporaryDirectory() as directory:
            result = subprocess.run([sys.executable, str(Path(__file__).with_name('guest.py')),
                                     '--smoke', '--output', directory,
                                     '--deadline-utc', '2000-01-01T00:00:00+00:00'],
                                    capture_output=True, timeout=10)
            self.assertEqual(result.returncode,1)
            report = json.loads((Path(directory)/'summary.json').read_text())
            self.assertEqual(report['results'],[])
            self.assertIn('deadline',report['error'])


if __name__ == '__main__':
    unittest.main()
