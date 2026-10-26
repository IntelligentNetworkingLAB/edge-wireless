import copy
import json
import os
import sys
import threading
import unittest
import urllib.error
import urllib.request
from http.server import ThreadingHTTPServer

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
sys.path.insert(0, ROOT)

from wireless import evaluate, web                              # noqa: E402

A = os.path.join(ROOT, 'config', 'assumptions.json')
M = os.path.join(ROOT, 'config', 'inputs.json')


def val(res, item):
    return next(i for i in res['items'] if i['id'] == item)['value']


class Model(unittest.TestCase):
    def setUp(self):
        self.m = web.Model(A, M)

    def test_defaults_reproduce_the_cli_result(self):
        cli = evaluate.run(A, M)
        got = self.m.compute()
        for i in cli['items']:
            self.assertAlmostEqual(val(got, i['id']), i['value'], places=9)
        self.assertEqual(got['changed'], [])

    def test_every_knob_default_matches_the_assumption_file(self):
        a = evaluate.load(A)
        m = evaluate.load(M)
        for k in self.m.knobs():
            spec = next(x for x in web.KNOBS if x['id'] == k['id'])
            root, path = (m, spec['path'][1:]) if spec['path'][0] == 'inputs' else (a, spec['path'])
            self.assertAlmostEqual(k['default'] * k['scale'], web._get(root, path))
            self.assertGreaterEqual(k['default'], k['min'] - 1e-9)
            self.assertLessEqual(k['default'], k['max'] + 1e-9)

    def test_each_knob_has_a_reason(self):
        for k in self.m.knobs():
            self.assertTrue(k['basis'], k['id'])

    def test_lower_sbs_load_lowers_energy_efficiency_and_can_fail_the_target(self):
        r = self.m.compute({'en_load': 0.4})
        self.assertLess(val(r, 'ee'), val(self.m.compute(), 'ee'))
        self.assertFalse(next(i for i in r['items'] if i['id'] == 'ee')['ok'])
        self.assertEqual(r['changed'], ['en_load'])

    def test_removing_the_mimo_gain_pulls_downlink_below_target(self):
        r = self.m.compute({'dl_mimo': 4.0})
        self.assertLess(val(r, 'se_dl'), 30.0)

    def test_downlink_change_flows_into_rate_and_energy(self):
        base = self.m.compute()
        r = self.m.compute({'dl_mimo': 4.0})
        self.assertLess(val(r, 'rate'), val(base, 'rate'))
        self.assertLess(val(r, 'ee'), val(base, 'ee'))

    def test_bandwidth_slider_is_in_mhz(self):
        k = next(x for x in self.m.knobs() if x['id'] == 'rate_bw')
        self.assertEqual(k['default'], 100.0)
        r = self.m.compute({'rate_bw': 50})
        self.assertAlmostEqual(val(r, 'rate') / val(self.m.compute(), 'rate'), 0.5, places=3)

    def test_cache_hit_slider_changes_energy(self):
        hi = val(self.m.compute({'hit': 90}), 'ee')
        lo = val(self.m.compute({'hit': 10}), 'ee')
        self.assertGreater(hi, lo)

    def test_out_of_range_and_unknown_knobs_are_rejected(self):
        with self.assertRaises(ValueError):
            self.m.compute({'en_load': 5})
        with self.assertRaises(KeyError):
            self.m.compute({'nope': 1})

    def test_compute_does_not_mutate_the_loaded_assumptions(self):
        before = copy.deepcopy(self.m.a0)
        self.m.compute({'dl_mimo': 4.0, 'en_load': 0.3, 'hit': 5})
        self.assertEqual(before, self.m.a0)

    def test_energy_curve_crosses_the_target_where_the_crossover_says(self):
        r = self.m.compute()
        ee = next(i for i in r['items'] if i['id'] == 'ee')
        x = ee['detail']['crossover_load']
        below = [p for p in r['energy_curve'] if p['load'] < x - 0.03]
        above = [p for p in r['energy_curve'] if p['load'] > x + 0.03]
        self.assertTrue(all(p['ratio'] < ee['target'] for p in below))
        self.assertTrue(all(p['ratio'] >= ee['target'] for p in above))


class Http(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        web.Handler.model = web.Model(A, M)
        cls.httpd = ThreadingHTTPServer(('127.0.0.1', 0), web.Handler)
        threading.Thread(target=cls.httpd.serve_forever, daemon=True).start()
        cls.base = 'http://127.0.0.1:%d' % cls.httpd.server_address[1]

    @classmethod
    def tearDownClass(cls):
        cls.httpd.shutdown()
        cls.httpd.server_close()

    def call(self, path, body=None):
        data = None if body is None else json.dumps(body).encode('utf-8')
        req = urllib.request.Request(self.base + path, data=data,
                                     method='POST' if body is not None else 'GET')
        try:
            with urllib.request.urlopen(req, timeout=10) as r:
                return r.status, r.read()
        except urllib.error.HTTPError as e:
            try:
                return e.code, e.read()
            finally:
                e.close()

    def test_page_and_api(self):
        code, raw = self.call('/')
        self.assertEqual(code, 200)
        self.assertIn('산식값'.encode('utf-8'), raw)
        code, raw = self.call('/api/knobs')
        self.assertEqual(code, 200)
        self.assertGreater(len(json.loads(raw)), 10)
        code, raw = self.call('/api/evaluate', {'values': {'en_load': 0.5}})
        self.assertEqual(code, 200)
        self.assertEqual(json.loads(raw)['changed'], ['en_load'])

    def test_bad_input_is_a_400_not_a_crash(self):
        self.assertEqual(self.call('/api/evaluate', {'values': {'en_load': 9}})[0], 400)
        self.assertEqual(self.call('/api/evaluate', {'values': {'zzz': 1}})[0], 400)
        self.assertEqual(self.call('/api/nothing')[0], 404)


if __name__ == '__main__':
    unittest.main()
