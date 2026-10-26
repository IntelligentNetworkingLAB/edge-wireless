# 시뮬레이션 결과를 받아 5개 항목을 계산하고 판정한다.
#
# 시뮬레이션이 낸 값(payload, 처리량, 전력, 지연 등)을 CSV 로 넣으면 산식을
# 적용해서 스펙트럼 효율, Latency, Data Rate, 에너지 효율을 구하고 목표와 비교한다.
# 값을 새로 만들지 않고 입력값에 산식만 적용한다.
#
# 입력은 긴 형식 CSV 한 장이다: item, case, param, value
#   item   se_dl, se_ul, lat, rate, ee
#   case   baseline(기준 설정) 또는 proposed(제안 기법)
#   param  아래 ROUTES 에 있는 변수 이름
#
# 같은 값을 여러 방법으로 줄 수 있다. 직접 준 값이 있으면 그것을 쓰고, 없으면 산식으로 구한다.

import csv
import io

from . import targets

MAX_BYTES = 1024 * 1024

ITEM_ALIASES = {
    'se_dl': ('se_dl', 'dl', '하향', '하향스펙트럼효율', 'downlink'),
    'se_ul': ('se_ul', 'ul', '상향', '상향스펙트럼효율', 'uplink'),
    'lat': ('lat', 'latency', '지연', 'latency_ms'),
    'rate': ('rate', 'datarate', 'data_rate', '데이터레이트', '속도'),
    'ee': ('ee', 'energy', '에너지', '에너지효율'),
}
CASE_ALIASES = {
    'baseline': ('baseline', 'base', '기준', '기준설정', '기존'),
    'proposed': ('proposed', 'ours', 'proposal', '제안', '제안기법', '본과제'),
}
PARAMS = {
    'se': ('스펙트럼 효율', 'b/s/Hz'), 'throughput_mbps': ('처리량', 'Mb/s'),
    'payload_bits': ('Payload', 'bits'), 'slot_ms': ('슬롯 길이', 'ms'),
    'n_rb': ('자원블록 수', '개'), 'scs_khz': ('부반송파 간격', 'kHz'),
    'latency_ms': ('지연', 'ms'), 'rate_mbps': ('사용자 속도', 'Mb/s'),
    'bw_mhz': ('할당 대역폭', 'MHz'), 'users': ('동시 스케줄 사용자', '명'),
    'power_w': ('총 전력', 'W'), 'ee_ratio': ('에너지 효율 개선 배수', '배'),
}
PARAM_ALIASES = {
    'se': ('se', 'spectral_efficiency', '스펙트럼효율'),
    'throughput_mbps': ('throughput_mbps', 'throughput', 'tp_mbps', '처리량'),
    'payload_bits': ('payload_bits', 'payload', 'payload(bits)'),
    'slot_ms': ('slot_ms', 'timeslot_ms', 'slot', 'tti_ms_slot'),
    'n_rb': ('n_rb', 'rb', 'num_rb', 'no_of_rb', 'nrb'),
    'scs_khz': ('scs_khz', 'scs', 'subcarrier_khz', 'subcarrier_bw_khz'),
    'latency_ms': ('latency_ms', 'latency', 'delay_ms', 'tti_ms'),
    'rate_mbps': ('rate_mbps', 'rate', 'user_rate_mbps'),
    'bw_mhz': ('bw_mhz', 'bandwidth_mhz', 'bw'),
    'users': ('users', 'n_users', 'num_users', 'ue'),
    'power_w': ('power_w', 'power', 'watt', 'energy_w', '전력'),
    'ee_ratio': ('ee_ratio', 'ee_gain', 'energy_ratio'),
}

# 항목마다 값을 구하는 방법. 앞에서부터 직접 준 값이 있는 첫 번째 방법을 쓴다.
ROUTES = {
    'se_dl': [['se'], ['throughput_mbps', 'n_rb', 'scs_khz'], ['payload_bits', 'slot_ms', 'n_rb', 'scs_khz']],
    'se_ul': [['se'], ['throughput_mbps', 'n_rb', 'scs_khz'], ['payload_bits', 'slot_ms', 'n_rb', 'scs_khz']],
    'lat': [['latency_ms'], ['payload_bits', 'throughput_mbps']],
    'rate': [['rate_mbps'], ['throughput_mbps'], ['se', 'bw_mhz', 'users']],
    'ee': [['throughput_mbps', 'power_w']],
}
ITEM_ORDER = ['se_dl', 'se_ul', 'ee', 'rate', 'lat']
CASES = ('baseline', 'proposed')


def _alias_map(table):
    out = {}
    for canon, names in table.items():
        for n in names:
            out[n.replace(' ', '').lower()] = canon
    return out


_ITEM, _CASE, _PARAM = _alias_map(ITEM_ALIASES), _alias_map(CASE_ALIASES), _alias_map(PARAM_ALIASES)
_HEAD = {'item': ('item', '항목'), 'case': ('case', '구분', '케이스'),
         'param': ('param', 'parameter', '변수', '파라미터'), 'value': ('value', '값')}


def parse(text):
    """CSV 를 {item: {case: {param: value}}} 로 바꾼다. 경고 목록을 같이 돌려준다."""
    if len(text.encode('utf-8')) > MAX_BYTES:
        raise ValueError('입력이 너무 크다 (1 MB 까지)')
    text = text.strip('﻿\r\n ')
    if not text:
        raise ValueError('입력이 비어 있다')
    delim = '\t' if text[:1000].count('\t') > text[:1000].count(',') else ','
    rows = [r for r in csv.reader(io.StringIO(text), delimiter=delim) if any(c.strip() for c in r)]
    heads = [h.strip().lower().lstrip('﻿') for h in rows[0]]
    idx = {}
    for canon, names in _HEAD.items():
        for i, h in enumerate(heads):
            if h in names:
                idx[canon] = i
                break
    missing = [k for k in _HEAD if k not in idx]
    if missing:
        raise ValueError('헤더에 item, case, param, value 열이 있어야 한다 (없는 열: %s). 받은 헤더: %s'
                         % (', '.join(missing), ', '.join(heads)))
    data, warnings, seen = {}, [], set()
    for ln, r in enumerate(rows[1:], 2):
        if len(r) <= max(idx.values()):
            raise ValueError('%d번째 줄의 열 수가 헤더보다 적다' % ln)
        it = _ITEM.get(r[idx['item']].replace(' ', '').lower())
        ca = _CASE.get(r[idx['case']].replace(' ', '').lower())
        pa = _PARAM.get(r[idx['param']].replace(' ', '').lower())
        if it is None:
            warnings.append('%d번째 줄: 모르는 항목 %r 는 무시했다 (se_dl, se_ul, lat, rate, ee)' % (ln, r[idx['item']]))
            continue
        if ca is None:
            raise ValueError('%d번째 줄의 구분은 baseline 또는 proposed 여야 한다: %r' % (ln, r[idx['case']]))
        if pa is None:
            warnings.append('%d번째 줄: 모르는 변수 %r 는 무시했다' % (ln, r[idx['param']]))
            continue
        try:
            v = float(r[idx['value']].strip().replace(',', ''))
        except ValueError:
            raise ValueError('%d번째 줄의 값이 숫자가 아니다: %r' % (ln, r[idx['value']]))
        if v <= 0:
            raise ValueError('%d번째 줄: %s 는 0 보다 커야 한다 (%s)' % (ln, PARAMS[pa][0], v))
        key = (it, ca, pa)
        if key in seen:
            warnings.append('%d번째 줄: %s/%s/%s 가 중복이라 뒤의 값을 썼다' % (ln, it, ca, pa))
        seen.add(key)
        data.setdefault(it, {}).setdefault(ca, {})[pa] = v
    return data, warnings, len(rows) - 1


def _fmt(v, d=2):
    if abs(v) >= 1e9:
        return '%.3f G' % (v / 1e9)
    return ('%.' + str(d) + 'f') % v


def _bps(b):
    return '%.3f Gb/s' % (b / 1e9) if b >= 1e9 else '%.1f Mb/s' % (b / 1e6)


def _route(item, p):
    """직접 준 값이 있는 첫 번째 방법을 돌려준다."""
    for r in ROUTES[item]:
        if all(k in p for k in r):
            return r
    return None


def _se(p):
    r = _route('se_dl', p)
    if r is None:
        return None
    if r == ['se']:
        return {'value': p['se'], 'how': '직접 입력', 'lines': ['스펙트럼 효율 = %s b/s/Hz (입력값)' % _fmt(p['se'])]}
    bw_hz = 12 * p['n_rb'] * p['scs_khz'] * 1e3
    lines = []
    if r[0] == 'throughput_mbps':
        tp = p['throughput_mbps'] * 1e6
        lines.append('Throughput = %s (입력값)' % _bps(tp))
    else:
        tp = p['payload_bits'] / (p['slot_ms'] * 1e-3)
        lines.append('Throughput = Payload / Timeslot = %s bits / %s ms = %s'
                     % (format(int(round(p['payload_bits'])), ','), _fmt(p['slot_ms'], 3), _bps(tp)))
    se = tp / bw_hz
    lines.append('SE = Throughput / (12 × RB × SCS) = %s / (12 × %s × %s kHz = %s MHz) = %s b/s/Hz'
                 % (_bps(tp), _fmt(p['n_rb'], 0), _fmt(p['scs_khz'], 0), _fmt(bw_hz / 1e6), _fmt(se)))
    return {'value': se, 'how': '산식 적용', 'lines': lines}


def _lat(p):
    r = _route('lat', p)
    if r is None:
        return None
    if r == ['latency_ms']:
        return {'value': p['latency_ms'], 'how': '직접 입력', 'lines': ['Latency = %s ms (입력값)' % _fmt(p['latency_ms'], 4)]}
    ms = p['payload_bits'] / (p['throughput_mbps'] * 1e3)
    return {'value': ms, 'how': '산식 적용',
            'lines': ['Latency = Payload / Throughput = %s bits / %s kb/s = %s ms'
                      % (format(int(round(p['payload_bits'])), ','), _fmt(p['throughput_mbps'] * 1e3, 0), _fmt(ms, 4))]}


def _rate(p):
    r = _route('rate', p)
    if r is None:
        return None
    if r == ['rate_mbps']:
        return {'value': p['rate_mbps'], 'how': '직접 입력', 'lines': ['사용자 속도 = %s Mb/s (입력값)' % _fmt(p['rate_mbps'], 1)]}
    if r == ['throughput_mbps']:
        return {'value': p['throughput_mbps'], 'how': 'Peak User Throughput',
                'lines': ['Peak User Experienced Throughput = %s Mb/s (입력값)' % _fmt(p['throughput_mbps'], 1)]}
    v = p['se'] * p['bw_mhz'] / p['users']
    return {'value': v, 'how': '산식 적용',
            'lines': ['사용자 속도 = SE × 대역폭 / 사용자 수 = %s b/s/Hz × %s MHz / %s명 = %s Mb/s'
                      % (_fmt(p['se']), _fmt(p['bw_mhz'], 0), _fmt(p['users'], 0), _fmt(v, 1))]}


def _ee(p):
    if not all(k in p for k in ('throughput_mbps', 'power_w')):
        return None
    v = p['throughput_mbps'] / p['power_w']
    return {'value': v, 'how': '산식 적용',
            'lines': ['EE = Throughput / Total Energy = %s Mb/s / %s W = %s Mb/s/W'
                      % (_fmt(p['throughput_mbps'], 1), _fmt(p['power_w'], 1), _fmt(v, 4))]}


CALC = {'se_dl': _se, 'se_ul': _se, 'lat': _lat, 'rate': _rate, 'ee': _ee}


def _need(item):
    if item == 'ee':
        return ['throughput_mbps + power_w (기준과 제안 둘 다) 또는 제안의 ee_ratio']
    return [' + '.join(r) for r in ROUTES[item]]


def evaluate(text):
    data, warnings, n_rows = parse(text)
    items = []
    for iid in ITEM_ORDER:
        t = targets.BY_ID[iid]
        by = data.get(iid, {})
        res = {'id': iid, 'label': t['label'], 'unit': t['unit'], 'ref': t['ref'],
               'ref_src': t['ref_src'], 'target': t['target'], 'dir': t['dir'],
               'value': None, 'baseline': None, 'gain': None,
               'ok': None, 'margin': None, 'status': 'missing', 'proposed': None, 'base': None,
               'lines': [], 'need': _need(iid)}
        base = CALC[iid](by.get('baseline', {})) if by.get('baseline') else None
        prop = CALC[iid](by.get('proposed', {})) if by.get('proposed') else None
        res['base'], res['proposed'] = base, prop
        if iid == 'ee':
            pr = by.get('proposed', {})
            if 'ee_ratio' in pr:
                res['value'] = pr['ee_ratio']
                res['lines'].append('개선 배수 = %s 배 (입력값)' % _fmt(pr['ee_ratio'], 2))
            elif base and prop:
                res['value'] = prop['value'] / base['value']
                res['baseline'] = base['value']
                res['lines'] += ['기준: ' + base['lines'][0], '제안: ' + prop['lines'][0],
                                 '개선 배수 = %s / %s = %s 배' % (_fmt(prop['value'], 4), _fmt(base['value'], 4),
                                                              _fmt(res['value'], 2))]
            elif prop and not base:
                warnings.append('ee: 기준(baseline) 처리량과 전력이 없어 개선 배수를 못 구했다.')
        else:
            if prop:
                res['value'] = prop['value']
                res['lines'] += ['제안: ' + ln for ln in prop['lines']]
            if base:
                res['baseline'] = base['value']
                res['lines'] += ['기준: ' + ln for ln in base['lines']]
                if prop:
                    res['gain'] = (base['value'] / prop['value']) if t['dir'] == 'down' else (prop['value'] / base['value'])
                    res['lines'].append('기준 대비 %s 배 %s' % (_fmt(res['gain'], 2), '빨라졌다' if t['dir'] == 'down' else '높아졌다'))
                lo, hi = t['ref'] * 0.75, t['ref'] * 1.25
                if iid != 'ee' and not (lo <= base['value'] <= hi):
                    warnings.append('%s: 입력한 기준값 %s 이 기준 수준 %s %s (%s) 과 25%% 넘게 다르다. 비교 기준이 맞는지 확인할 것.'
                                    % (iid, _fmt(base['value'], 3), t['ref'], t['unit'], t['ref_src']))
        v = res['value']
        if v is not None:
            res['status'] = 'ok'
            if t['dir'] == 'up':
                res['ok'], res['margin'] = v >= t['target'], 100.0 * (v / t['target'] - 1.0)
            else:
                res['ok'], res['margin'] = v <= t['target'], 100.0 * (t['target'] / v - 1.0)
        elif by:
            res['status'] = 'incomplete'
        items.append(res)
    ev = [i for i in items if i['status'] == 'ok']
    return {'items': items, 'passed': sum(1 for i in ev if i['ok']), 'evaluated': len(ev),
            'total': len(items), 'warnings': warnings, 'n_rows': n_rows}


def rows_from(text):
    """CSV 를 화면 표의 행으로 바꾼다. 별칭은 표준 이름으로 바꿔서 돌려준다."""
    data, warnings, _ = parse(text)
    rows = [{'item': i, 'case': c, 'param': k, 'value': v}
            for i in ITEM_ORDER for c in CASES for k, v in data.get(i, {}).get(c, {}).items()]
    return {'rows': rows, 'warnings': warnings}


def format_info():
    return {'routes': ROUTES, 'params': {k: {'label': v[0], 'unit': v[1]} for k, v in PARAMS.items()},
            'items': {i: {'label': targets.BY_ID[i]['label'], 'unit': targets.BY_ID[i]['unit'],
                          'target': targets.BY_ID[i]['target'], 'ref': targets.BY_ID[i]['ref'],
                          'dir': targets.BY_ID[i]['dir']} for i in ITEM_ORDER},
            'order': ITEM_ORDER, 'cases': list(CASES),
            'header': 'item,case,param,value'}


def sample_csv(a, m):
    """가정 JSON 으로 만든 예시 시뮬레이션 결과. 입력 형식을 보이는 용도이며 실제 시뮬레이터 출력이 아니다."""
    from . import radio
    rows = []

    def add(item, case, **kv):
        for k, v in kv.items():
            rows.append((item, case, k, v))

    waters = {}
    for iid in ('se_dl', 'se_ul'):
        link = a['links'][iid]
        w = waters[iid] = radio.waterfall(link['base'], link['steps'])
        for case, row in (('baseline', w[0]), ('proposed', w[-1])):
            c = row['cfg']
            add(iid, case, payload_bits=round(radio.payload_bits(c), 1), slot_ms=c['slot_ms'],
                n_rb=c['n_rb'], scs_khz=round(c['scs_hz'] / 1e3, 3))
    L = a['latency']
    add('lat', 'baseline', latency_ms=round(radio.latency_parts(L['base'])['tti'], 6))
    add('lat', 'proposed', latency_ms=round(radio.latency_parts(L['ours'])['tti'], 6))
    se_b, se_o = waters['se_dl'][0]['value'], waters['se_dl'][-1]['value']
    R = a['rate']
    add('rate', 'baseline', se=round(se_b, 4), bw_mhz=R['base']['bw_hz'] / 1e6, users=R['base']['users'])
    add('rate', 'proposed', se=round(se_o, 4), bw_mhz=R['ours']['bw_hz'] / 1e6, users=R['ours']['users'])
    hit = (m.get('cache_hit') or {}).get('value_pct', 0.0) / 100.0
    b = radio.energy_baseline(a['energy'], se_b)
    o = radio.energy_ours(a['energy'], se_b, se_o, hit)
    add('ee', 'baseline', throughput_mbps=round(b['tp_bps'] / 1e6, 2), power_w=round(b['p_total_w'], 2))
    add('ee', 'proposed', throughput_mbps=round(o['tp_bps'] / 1e6, 2), power_w=round(o['p_total_w'], 2))
    out = ['item,case,param,value']
    out += ['%s,%s,%s,%s' % (i, c, k, '%.10g' % v) for i, c, k, v in rows]
    return '\n'.join(out) + '\n'
