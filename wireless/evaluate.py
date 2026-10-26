# 무선 5개 항목을 산출하고 목표 대비 판정한다.
#
# 산출 결과에는 값과 함께 근거 등급과 계산 과정을 담는다.
# 보고서 렌더러는 이 구조만 읽고 계산은 하지 않는다.
#
# 근거 등급
#   calc   산식 + assumptions.json 으로 계산한 값
#   none   입력이 없어 계산하지 않음

import json
import os

from . import radio, targets

GRADE_LABEL = {'calc': '산식'}


def load(path):
    with open(path, encoding='utf-8') as f:
        return json.load(f)


def verdict(value, target, direction):
    """목표 달성 여부와 여유분. 미달이면 미달로 돌려준다."""
    if value is None:
        return None, None
    if direction == 'up':
        return value >= target, 100.0 * (value / target - 1.0)
    return value <= target, 100.0 * (target / value - 1.0)


def _item(tid, value, grade, detail):
    t = dict(targets.BY_ID[tid])
    ok, margin = verdict(value, t['target'], t['dir'])
    t.update({'value': value, 'grade': grade, 'ok': ok, 'margin': margin,
              'grade_label': GRADE_LABEL[grade], 'detail': detail})
    return t


# ------------------------------------------------------------ 무선 구간

def eval_spectral(a, tid):
    link = a['links'][tid]
    rows = radio.waterfall(link['base'], link['steps'])
    base = rows[0]
    detail = {
        'formula': [targets.FORMULAS['payload'], targets.FORMULAS['tp'],
                    targets.FORMULAS['se']],
        'base_cfg': link['base'],
        'base_substitution': {
            're_per_rb': ((radio.SYM_PER_SLOT - base['cfg']['ctrl_sym'])
                          * radio.RE_PER_SYM - base['cfg']['ce_re']),
            'payload_bits': radio.payload_bits(base['cfg']),
            'throughput_bps': radio.throughput_bps(base['cfg']),
            'channel_bw_hz': radio.channel_bw_hz(base['cfg']),
            'value': base['value'],
        },
        'steps': [{k: r[k] for k in
                   ('label', 'module', 'basis', 'value', 'factor', 'changed')}
                  for r in rows],
    }
    return _item(tid, rows[-1]['value'], 'calc', detail)


def eval_latency(a):
    L = a['latency']
    b, o = radio.latency_parts(L['base']), radio.latency_parts(L['ours'])
    detail = {
        'formula': [targets.FORMULAS['lat'], targets.FORMULAS['tp']],
        'note': 'Throughput = Payload / TTI 이므로 Latency = TTI 로 정리된다. '
                '이 산식이 재는 값은 무선 구간 전송 단위 시간이다.',
        'base': b, 'ours': o,
        'base_cfg': L['base'], 'ours_cfg': L['ours'],
        'caveat': L.get('caveat', ''),
    }
    return _item('lat', o['tti'], 'calc', detail)


def eval_rate(a, se_base, se_ours, hit):
    R = a['rate']
    sb = dict(R['base']); sb['se'] = se_base
    so = dict(R['ours']); so['se'] = se_ours
    rb, ro = radio.user_rate_bps(sb), radio.user_rate_bps(so)
    detail = {
        'formula': [('사용자 속도', '스펙트럼 효율 x 할당 대역폭 / 동시 스케줄 사용자 수')],
        'formula_note': '사용자 속도 산식은 따로 없어서 셀 용량을 '
                        '동시 스케줄 사용자가 나눠 쓴다는 표준 정의를 썼고, '
                        '스펙트럼 효율은 위의 산식으로 구한 값이다.',
        'base': dict(sb, value_bps=rb), 'ours': dict(so, value_bps=ro),
        'note': '피크값 기준으로 보고한다.',
    }
    if hit is not None:
        detail['delivered'] = {
            'backhaul_bps': R['backhaul_bps'],
            'backhaul_basis': R.get('backhaul_basis', ''),
            'ours_bps': radio.delivered_rate_bps(ro, R['backhaul_bps'],
                                                 hit['value_pct'] / 100.0),
            'base_bps': radio.delivered_rate_bps(ro, R['backhaul_bps'],
                                                 hit['baseline_pct'] / 100.0),
            'hit': hit,
        }
    return _item('rate', ro / 1e6, 'calc', detail)


def eval_energy(a, se_base, se_ours, hit):
    e = a['energy']
    ratio_hit = 0.0 if hit is None else hit['value_pct'] / 100.0
    b = radio.energy_baseline(e, se_base)
    o = radio.energy_ours(e, se_base, se_ours, ratio_hit)
    want = targets.BY_ID['ee']['target']
    sweep = [{'load': l,
              'ratio': radio.energy_ratio(e, se_base, se_ours, ratio_hit, l)}
             for l in e['sweep_loads']]
    detail = {
        'formula': [targets.FORMULAS['ee'],
                    ('선형 전력 모델', 'P_in = P0 + dp x P_out')],
        'formula_note': '첫 줄만 평가 산식이다. 전력 모델은 산식에 없어서 '
                        '기지국 전력을 다루는 표준 모델을 가져왔고 출처는 '
                        '아래 근거에 적었다.',
        'basis': e.get('basis', ''),
        'baseline': b, 'ours': o, 'hit_ratio': ratio_hit,
        'se_gain': se_ours / se_base,
        'crossover_load': radio.energy_crossover_load(e, se_base, se_ours,
                                                      ratio_hit, want),
        'sweep': sweep,
        'note': '지배항은 셀 축소다. MBS 한 대가 큰 전력으로 커버하던 영역을 '
                'SBS 여러 대가 나눠 맡으면 공간 재사용으로 처리량이 늘면서 '
                '전력은 오히려 줄어든다. 스펙트럼 효율 개선은 그 위에 얹히는 '
                '2차 항이고, 캐싱은 백홀 전력을 깎는 쪽으로 기여한다.',
    }
    return _item('ee', o['ee_bps_w'] / b['ee_bps_w'], 'calc', detail)


# ------------------------------------------------------------ 학습 지표

# ------------------------------------------------------------ 전체

def warnings_for(items, hit):
    w = []
    bad = [i['label'] for i in items if i['ok'] is False]
    if bad:
        w.append('목표 미달 항목: ' + ', '.join(bad))
    if hit is None:
        w.append('캐시 히트율 입력이 없다. 에너지 효율은 캐시 효과 없이 계산했고 '
                 '체감 Data Rate 참고값은 생략했다. inputs.json 의 cache_hit 를 '
                 '채울 것.')
    elif not hit.get('source'):
        w.append('cache_hit 에 source 가 비어 있다. 출처를 적어야 한다.')
    return w


def run(assumptions_path, inputs_path):
    return compute(load(assumptions_path), load(inputs_path),
                   {'assumptions': os.path.abspath(assumptions_path),
                    'inputs': os.path.abspath(inputs_path)})


def compute(a, m, sources):
    """가정 a 와 입력 m 으로 5개 항목을 계산한다. 파일을 읽지 않는다."""
    hit = m.get('cache_hit')
    if hit and hit.get('value_pct') is None:
        hit = None

    dl = eval_spectral(a, 'se_dl')
    ul = eval_spectral(a, 'se_ul')
    se_base = dl['detail']['steps'][0]['value']
    se_ours = dl['value']

    items = [dl, ul,
             eval_energy(a, se_base, se_ours, hit),
             eval_rate(a, se_base, se_ours, hit),
             eval_latency(a)]
    order = [t['id'] for t in targets.ITEMS]
    items.sort(key=lambda x: order.index(x['id']))

    return {
        'items': items,
        'assumptions': a,
        'cache_hit': hit,
        'passed': sum(1 for i in items if i['ok']),
        'total': len(items),
        'warnings': warnings_for(items, hit),
        'sources': sources,
    }
