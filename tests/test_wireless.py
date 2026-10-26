# 무선 평가 도구 단위 테스트.
#
#   python -m unittest discover -s tests -v
#   python -m pytest tests
#
# 목표치 달성 여부는 테스트하지 않는다. 산식이 정의와 같은지, 입력이 결과에
# 반영되는지, 미달이 미달로 판정되는지를 확인한다.

import copy
import json
import os
import sys
import tempfile
import unittest

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.dirname(HERE))

from wireless import evaluate, radio, render, targets    # noqa: E402

CFG = os.path.join(os.path.dirname(HERE), 'config')
A_PATH = os.path.join(CFG, 'assumptions.json')
M_PATH = os.path.join(CFG, 'inputs.json')


def load(p):
    with open(p, encoding='utf-8') as f:
        return json.load(f)


class Radio(unittest.TestCase):
    def test_payload_matches_proposal_formula(self):
        c = {'n_rb': 2, 'scs_hz': 30000, 'slot_ms': 0.5, 'ctrl_sym': 2,
             'ce_re': 12, 'bits_per_sym': 4, 'code_rate': 0.5,
             'mimo_gain': 2}
        # [(14-2)*12 - 12] * 4 * 2 * 0.5 * 2 = 132 * 8
        self.assertAlmostEqual(radio.payload_bits(c), 1056.0)
        self.assertAlmostEqual(radio.throughput_bps(c), 1056.0 / 5e-4)
        self.assertAlmostEqual(radio.spectral_eff(c),
                               radio.throughput_bps(c) / (12 * 2 * 30000))

    def test_payload_rejects_impossible_overhead(self):
        c = {'n_rb': 1, 'scs_hz': 30000, 'slot_ms': 0.5, 'ctrl_sym': 2,
             'ce_re': 999, 'bits_per_sym': 4, 'code_rate': 0.5,
             'mimo_gain': 1}
        with self.assertRaises(ValueError):
            radio.payload_bits(c)

    def test_apply_rejects_unknown_parameter(self):
        a = load(A_PATH)
        with self.assertRaises(KeyError):
            radio.apply(a['links']['se_dl']['base'], {'코드레이트': 0.9})

    def test_latency_formula_reduces_to_tti(self):
        a = load(A_PATH)
        # 산식은 Payload/Throughput 이고 Throughput 이 Payload/TTI 다
        self.assertAlmostEqual(radio.latency_parts(a['latency']['base'])['tti'],
                               1.0)
        p = radio.latency_parts(a['latency']['ours'])
        self.assertAlmostEqual(p['total'], p['tti'] + p['align'] + p['harq'])

    def test_delivered_rate_rises_with_hit_ratio(self):
        lo = radio.delivered_rate_bps(1e9, 3e8, 0.50)
        hi = radio.delivered_rate_bps(1e9, 3e8, 0.70)
        self.assertGreater(hi, lo)

    def test_energy_ratio_is_monotonic_in_load(self):
        a = load(A_PATH)
        e = a['energy']
        r = [radio.energy_ratio(e, 19.6, 30.0, 0.62, l)
             for l in (0.3, 0.5, 0.7, 0.9)]
        self.assertEqual(r, sorted(r))

    def test_energy_crossover_is_consistent_with_the_sweep(self):
        a = load(A_PATH)
        e = a['energy']
        x = radio.energy_crossover_load(e, 19.6, 30.0, 0.62, 30.0)
        self.assertIsNotNone(x)
        self.assertGreaterEqual(radio.energy_ratio(e, 19.6, 30.0, 0.62,
                                                   x + 0.01), 30.0)
        self.assertLess(radio.energy_ratio(e, 19.6, 30.0, 0.62, x - 0.01),
                        30.0)

    def test_crossover_is_none_when_unreachable(self):
        a = load(A_PATH)
        self.assertIsNone(radio.energy_crossover_load(
            a['energy'], 19.6, 30.0, 0.62, 10000.0))


class Targets(unittest.TestCase):
    def test_five_radio_items_have_reference_and_target(self):
        self.assertEqual(len(targets.ITEMS), 5)
        for t in targets.ITEMS:
            self.assertIn(t['dir'], ('up', 'down'))
            self.assertTrue(t['ref_src'])
            self.assertNotIn('yearly', t)

    def test_target_is_better_than_the_reference(self):
        for t in targets.ITEMS:
            if t['dir'] == 'up':
                self.assertGreater(t['target'], t['ref'], t['id'])
            else:
                self.assertLess(t['target'], t['ref'], t['id'])


class Evaluation(unittest.TestCase):
    def setUp(self):
        self.res = evaluate.run(A_PATH, M_PATH)

    def test_baseline_settings_land_near_the_published_reference(self):
        # 기준 설정 산출값이 기준 수준 근처여야 개선분을 비교할 수 있다
        for tid in ('se_dl', 'se_ul'):
            it = next(x for x in self.res['items'] if x['id'] == tid)
            base = it['detail']['steps'][0]['value']
            self.assertTrue(0.9 * it['ref'] <= base <= 1.2 * it['ref'],
                            '%s 기준 %.2f' % (tid, base))

    def test_every_step_only_improves_and_carries_a_module_and_basis(self):
        for tid in ('se_dl', 'se_ul'):
            it = next(x for x in self.res['items'] if x['id'] == tid)
            for r in it['detail']['steps'][1:]:
                self.assertGreaterEqual(r['factor'], 1.0, r['label'])
                self.assertTrue(r['module'], r['label'])
                self.assertGreater(len(r['basis']), 40, r['label'])

    def test_all_items_are_graded_and_judged(self):
        self.assertEqual(len(self.res['items']), 5)
        for it in self.res['items']:
            self.assertEqual(it['grade'], 'calc')
            self.assertIn(it['ok'], (True, False))

    def test_shortfalls_are_reported_not_hidden(self):
        bad = [i for i in self.res['items'] if i['ok'] is False]
        if bad:
            joined = ' '.join(self.res['warnings'])
            for b in bad:
                self.assertIn(b['label'], joined)

    def test_assumption_change_moves_the_result(self):
        a = copy.deepcopy(load(A_PATH))
        a['links']['se_dl']['steps'][-1]['set']['mimo_gain'] = 4.0
        with tempfile.NamedTemporaryFile('w', suffix='.json', delete=False,
                                         encoding='utf-8') as f:
            json.dump(a, f)
            path = f.name
        try:
            res = evaluate.run(path, M_PATH)
            it = next(x for x in res['items'] if x['id'] == 'se_dl')
            base = next(x for x in self.res['items'] if x['id'] == 'se_dl')
            self.assertLess(it['value'], base['value'])
        finally:
            os.unlink(path)

    def test_missing_cache_hit_is_warned_and_lowers_energy(self):
        m = copy.deepcopy(load(M_PATH))
        m.pop('cache_hit')
        with tempfile.NamedTemporaryFile('w', suffix='.json', delete=False,
                                         encoding='utf-8') as f:
            json.dump(m, f)
            path = f.name
        try:
            res = evaluate.run(A_PATH, path)
            self.assertTrue(any('캐시 히트율' in w for w in res['warnings']))
            ee = next(x for x in res['items'] if x['id'] == 'ee')
            base = next(x for x in self.res['items'] if x['id'] == 'ee')
            self.assertLess(ee['value'], base['value'])
        finally:
            os.unlink(path)

    def test_missing_source_is_flagged(self):
        m = copy.deepcopy(load(M_PATH))
        m['cache_hit']['source'] = ''
        with tempfile.NamedTemporaryFile('w', suffix='.json', delete=False,
                                         encoding='utf-8') as f:
            json.dump(m, f)
            path = f.name
        try:
            res = evaluate.run(A_PATH, path)
            self.assertTrue(any('source' in w for w in res['warnings']))
        finally:
            os.unlink(path)


class Render(unittest.TestCase):
    def setUp(self):
        self.res = evaluate.run(A_PATH, M_PATH)

    def test_text_report_lists_every_item(self):
        out = render.text(self.res)
        for it in self.res['items']:
            self.assertIn(it['label'], out)

    def test_html_is_self_contained(self):
        out = render.html(self.res)
        self.assertTrue(out.startswith('<!DOCTYPE html>'))
        # 외부 파일을 참조하지 않는 단독 HTML 이어야 한다
        self.assertNotIn('<link', out)
        self.assertNotIn('<script', out)
        self.assertIn('prefers-color-scheme', out)

    def test_markdown_has_the_summary_table(self):
        out = render.markdown(self.res)
        self.assertIn('| 항목 |', out)
        self.assertIn('| 기준 수준 | 목표 |', out)

    def test_json_round_trips(self):
        s = json.dumps(self.res, ensure_ascii=False)
        self.assertEqual(json.loads(s)['total'], 5)

    def test_east_asian_padding_counts_wide_characters(self):
        self.assertEqual(render.dw('가나'), 4)
        self.assertEqual(render.dw('ab'), 2)
        self.assertEqual(render.dw(render.pad('가', 6)), 6)


if __name__ == '__main__':
    unittest.main(verbosity=2)
