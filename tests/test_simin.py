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

from wireless import evaluate, simin, web                       # noqa: E402

A = os.path.join(ROOT, 'config', 'assumptions.json')
M = os.path.join(ROOT, 'config', 'inputs.json')
HEAD = 'item,case,param,value\n'


def item(res, iid):
    return next(i for i in res['items'] if i['id'] == iid)


class Parse(unittest.TestCase):
    def test_aliases_and_korean_headers(self):
        d, w, n = simin.parse('항목,구분,변수,값\n하향,제안,스펙트럼효율,31\n지연,기준,latency,1')
        self.assertEqual(d['se_dl']['proposed']['se'], 31.0)
        self.assertEqual(d['lat']['baseline']['latency_ms'], 1.0)
        self.assertEqual(n, 2)

    def test_tab_delimited_and_thousands_separator(self):
        d, _, _ = simin.parse('item\tcase\tparam\tvalue\nse_dl\tproposed\tpayload_bits\t"1,474,593"')
        self.assertEqual(d['se_dl']['proposed']['payload_bits'], 1474593.0)

    def test_unknown_names_are_ignored_with_a_warning(self):
        d, w, _ = simin.parse(HEAD + 'zzz,proposed,se,1\nse_dl,proposed,whatever,2\nse_dl,proposed,se,30')
        self.assertEqual(list(d), ['se_dl'])
        self.assertEqual(len(w), 2)

    def test_duplicates_use_the_later_value_and_warn(self):
        d, w, _ = simin.parse(HEAD + 'se_dl,proposed,se,10\nse_dl,proposed,se,12')
        self.assertEqual(d['se_dl']['proposed']['se'], 12.0)
        self.assertTrue(any('중복' in x for x in w))

    def test_bad_rows_name_the_line(self):
        for text, frag in ((HEAD + 'se_dl,proposed,se,abc', '2번째 줄'),
                           (HEAD + 'se_dl,wrong,se,1', 'baseline 또는 proposed'),
                           (HEAD + 'se_dl,proposed,n_rb,0', '0 보다 커야'),
                           (HEAD + 'se_dl,proposed,n_rb,-3', '0 보다 커야'),
                           ('a,b,c\n1,2,3', 'item, case, param, value'),
                           ('', '비어')):
            with self.assertRaises(ValueError) as c:
                simin.parse(text)
            self.assertIn(frag, str(c.exception))


class Compute(unittest.TestCase):
    def test_spectral_efficiency_from_payload_matches_p90(self):
        # Payload / Timeslot = Throughput, Throughput / (12 x RB x SCS) = SE
        r = simin.evaluate(HEAD + 'se_dl,proposed,payload_bits,964454\nse_dl,proposed,slot_ms,0.5\n'
                           'se_dl,proposed,n_rb,273\nse_dl,proposed,scs_khz,30')
        expect = (964454 / 0.5e-3) / (12 * 273 * 30e3)
        self.assertAlmostEqual(item(r, 'se_dl')['value'], expect, places=9)
        self.assertAlmostEqual(item(r, 'se_dl')['value'], 19.627, places=2)

    def test_three_routes_to_the_same_value_agree(self):
        base = 'se_dl,proposed,'
        a = simin.evaluate(HEAD + base + 'se,19.6267')
        b = simin.evaluate(HEAD + base + 'throughput_mbps,1928.908\n' + base + 'n_rb,273\n' + base + 'scs_khz,30')
        c = simin.evaluate(HEAD + base + 'payload_bits,964454\n' + base + 'slot_ms,0.5\n' + base + 'n_rb,273\n' + base + 'scs_khz,30')
        for r in (b, c):
            self.assertAlmostEqual(item(r, 'se_dl')['value'], item(a, 'se_dl')['value'], places=3)

    def test_direct_value_wins_over_derived(self):
        r = simin.evaluate(HEAD + 'se_dl,proposed,se,25\nse_dl,proposed,payload_bits,964454\n'
                           'se_dl,proposed,slot_ms,0.5\nse_dl,proposed,n_rb,273\nse_dl,proposed,scs_khz,30')
        self.assertEqual(item(r, 'se_dl')['value'], 25.0)
        self.assertEqual(item(r, 'se_dl')['proposed']['how'], '직접 입력')

    def test_latency_is_payload_over_throughput(self):
        r = simin.evaluate(HEAD + 'lat,proposed,payload_bits,964454\nlat,proposed,throughput_mbps,1928.908')
        self.assertAlmostEqual(item(r, 'lat')['value'], 0.5, places=6)

    def test_rate_routes(self):
        r = simin.evaluate(HEAD + 'rate,proposed,se,30\nrate,proposed,bw_mhz,100\nrate,proposed,users,3')
        self.assertAlmostEqual(item(r, 'rate')['value'], 1000.0)
        r = simin.evaluate(HEAD + 'rate,proposed,rate_mbps,1200')
        self.assertEqual(item(r, 'rate')['value'], 1200.0)

    def test_energy_efficiency_is_a_ratio_of_throughput_per_watt(self):
        r = simin.evaluate(HEAD + 'ee,baseline,throughput_mbps,100\nee,baseline,power_w,200\n'
                           'ee,proposed,throughput_mbps,3000\nee,proposed,power_w,100')
        self.assertAlmostEqual(item(r, 'ee')['value'], 60.0)           # (30 / 0.5)
        self.assertAlmostEqual(item(r, 'ee')['baseline'], 0.5)

    def test_energy_needs_the_baseline_unless_the_ratio_is_given(self):
        r = simin.evaluate(HEAD + 'ee,proposed,throughput_mbps,3000\nee,proposed,power_w,100')
        self.assertEqual(item(r, 'ee')['status'], 'incomplete')
        self.assertTrue(any('기준' in w for w in r['warnings']))
        r = simin.evaluate(HEAD + 'ee,proposed,ee_ratio,31')
        self.assertEqual(item(r, 'ee')['value'], 31.0)

    def test_status_distinguishes_missing_from_incomplete(self):
        r = simin.evaluate(HEAD + 'se_dl,proposed,n_rb,273')
        self.assertEqual(item(r, 'se_dl')['status'], 'incomplete')
        self.assertEqual(item(r, 'lat')['status'], 'missing')
        self.assertEqual((r['evaluated'], r['total']), (0, 5))
        self.assertTrue(item(r, 'se_dl')['need'])

    def test_targets_are_inclusive_in_the_right_direction(self):
        r = simin.evaluate(HEAD + 'se_dl,proposed,se,30\nlat,proposed,latency_ms,0.1\nrate,proposed,rate_mbps,1000\n'
                           'ee,proposed,ee_ratio,30')
        for iid in ('se_dl', 'lat', 'rate', 'ee'):
            self.assertTrue(item(r, iid)['ok'], iid)
        r = simin.evaluate(HEAD + 'se_dl,proposed,se,29.99\nlat,proposed,latency_ms,0.11')
        self.assertFalse(item(r, 'se_dl')['ok'])
        self.assertFalse(item(r, 'lat')['ok'])
        self.assertLess(item(r, 'lat')['margin'], 0)

    def test_baseline_far_from_the_published_reference_is_warned(self):
        r = simin.evaluate(HEAD + 'se_dl,baseline,se,10\nse_dl,proposed,se,30')
        self.assertTrue(any('25%' in w for w in r['warnings']))
        r = simin.evaluate(HEAD + 'se_dl,baseline,se,19.6\nse_dl,proposed,se,30')
        self.assertFalse(any('25%' in w for w in r['warnings']))

    def test_every_result_shows_the_substituted_formula(self):
        r = simin.evaluate(HEAD + 'rate,proposed,se,30\nrate,proposed,bw_mhz,100\nrate,proposed,users,3')
        self.assertTrue(any('30.00 b/s/Hz × 100 MHz / 3명' in l for l in item(r, 'rate')['lines']))


class Sample(unittest.TestCase):
    def test_sample_reproduces_the_cli_values(self):
        a, m = evaluate.load(A), evaluate.load(M)
        r = simin.evaluate(simin.sample_csv(a, m))
        cli = evaluate.run(A, M)
        self.assertEqual((r['passed'], r['evaluated']), (5, 5))
        for i in cli['items']:
            self.assertAlmostEqual(item(r, i['id'])['value'], i['value'], delta=abs(i['value']) * 2e-3)

    def test_rows_roundtrip_through_the_canonical_form(self):
        a, m = evaluate.load(A), evaluate.load(M)
        text = simin.sample_csv(a, m)
        rows = simin.rows_from(text)['rows']
        back = HEAD + ''.join('%s,%s,%s,%s\n' % (x['item'], x['case'], x['param'], x['value']) for x in rows)
        r1, r2 = simin.evaluate(text), simin.evaluate(back)
        for iid in simin.ITEM_ORDER:
            self.assertAlmostEqual(item(r1, iid)['value'], item(r2, iid)['value'])


def call(base, path, body=None):
    data = None if body is None else json.dumps(body).encode('utf-8')
    req = urllib.request.Request(base + path, data=data, method='POST' if body is not None else 'GET')
    try:
        with urllib.request.urlopen(req, timeout=10) as r:
            raw = r.read()
            return r.status, (json.loads(raw.decode('utf-8')) if 'json' in r.headers.get('Content-Type', '') else raw)
    except urllib.error.HTTPError as e:
        try:
            return e.code, json.loads(e.read().decode('utf-8'))
        finally:
            e.close()


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

    def test_sample_then_evaluate(self):
        code, raw = call(self.base, '/api/simin/sample')
        self.assertEqual(code, 200)
        self.assertTrue(raw.startswith(b'item,case,param,value'))
        code, d = call(self.base, '/api/simin', {'text': raw.decode('utf-8')})
        self.assertEqual((code, d['passed'], d['evaluated']), (200, 5, 5))

    def test_bad_input_is_400(self):
        code, d = call(self.base, '/api/simin', {'text': HEAD + 'se_dl,proposed,se,abc'})
        self.assertEqual(code, 400)
        self.assertIn('숫자가 아니다', d['error'])
        self.assertEqual(call(self.base, '/api/simin', {'text': ''})[0], 400)

    def test_format_and_rows_endpoints(self):
        code, d = call(self.base, '/api/simin/format')
        self.assertEqual(code, 200)
        self.assertEqual(d['order'], ['se_dl', 'se_ul', 'ee', 'rate', 'lat'])
        code, d = call(self.base, '/api/simin/rows', {'text': '항목,구분,변수,값\n하향,제안,스펙트럼효율,31'})
        self.assertEqual(d['rows'], [{'item': 'se_dl', 'case': 'proposed', 'param': 'se', 'value': 31.0}])

    def test_page_leads_with_the_input_tab(self):
        code, raw = call(self.base, '/')
        text = raw.decode('utf-8')
        self.assertLess(text.index('시뮬레이션 결과 입력'), text.index('가정으로 계산'))


if __name__ == '__main__':
    unittest.main()
