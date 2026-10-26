# 웹 인터페이스. 시뮬레이션 결과를 입력해 평가하고, 가정을 슬라이더로 바꾸면 5개 항목을 다시 계산한다.
#
# 계산은 CLI 와 같은 evaluate.compute 가 한다. 슬라이더 값은 가정의 사본에만 적용하고
# 원본 JSON 은 바꾸지 않는다. 화면에서 바꾼 값은 새로고침하면 원래대로 돌아온다.

import copy
import json
import os
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from urllib.parse import urlparse

from . import evaluate, radio, simin, targets

HERE = os.path.dirname(os.path.abspath(__file__))
WEB = os.path.join(HERE, 'web')


def _step(group, i):
    return ['links', group, 'steps', i]


# 슬라이더 목록. path 는 가정 JSON 안의 위치, basis 는 값의 근거다.
# scale 이 있으면 화면에는 값/scale 로 표시한다 (Hz -> MHz).
KNOBS = [
    {'id': 'dl_ce', 'item': 'se_dl', 'label': '하향 파일럿 오버헤드', 'unit': 'RE/RB',
     'path': _step('se_dl', 0) + ['set', 'ce_re'], 'min': 6, 'max': 24, 'step': 1,
     'step_of': _step('se_dl', 0), 'hint': '낮을수록 데이터에 쓰는 자원이 늘어난다. 기준은 24'},
    {'id': 'dl_bits', 'item': 'se_dl', 'label': '하향 변조 차수', 'unit': 'bit/심볼',
     'path': _step('se_dl', 1) + ['set', 'bits_per_sym'], 'min': 6, 'max': 10, 'step': 2,
     'step_of': _step('se_dl', 1), 'hint': '6=64QAM, 8=256QAM, 10=1024QAM. 기준은 8'},
    {'id': 'dl_rate', 'item': 'se_dl', 'label': '하향 부호율', 'unit': '',
     'path': _step('se_dl', 1) + ['set', 'code_rate'], 'min': 0.8, 'max': 0.95, 'step': 0.01,
     'step_of': _step('se_dl', 1), 'hint': '기준은 0.92'},
    {'id': 'dl_mimo', 'item': 'se_dl', 'label': '하향 랭크·빔 적응 이득', 'unit': '레이어 환산',
     'path': _step('se_dl', 2) + ['set', 'mimo_gain'], 'min': 4.0, 'max': 5.2, 'step': 0.1,
     'step_of': _step('se_dl', 2), 'hint': '4.0 이 이득 없음. 4.4 가 +10%'},
    {'id': 'ul_ce', 'item': 'se_ul', 'label': '상향 SRS/DMRS 오버헤드', 'unit': 'RE/RB',
     'path': _step('se_ul', 0) + ['set', 'ce_re'], 'min': 9, 'max': 36, 'step': 1,
     'step_of': _step('se_ul', 0), 'hint': '기준은 36'},
    {'id': 'ul_rate', 'item': 'se_ul', 'label': '상향 부호율', 'unit': '',
     'path': _step('se_ul', 1) + ['set', 'code_rate'], 'min': 0.85, 'max': 0.97, 'step': 0.01,
     'step_of': _step('se_ul', 1), 'hint': '기준은 0.92'},
    {'id': 'ul_mimo', 'item': 'se_ul', 'label': '상향 MU-MIMO 페어링 이득', 'unit': '레이어 환산',
     'path': _step('se_ul', 2) + ['set', 'mimo_gain'], 'min': 4.0, 'max': 6.4, 'step': 0.1,
     'step_of': _step('se_ul', 2), 'hint': '4.0 이 이득 없음. 5.2 가 +30%'},
    {'id': 'lat_sym', 'item': 'lat', 'label': '전송 단위 (mini-slot 심볼 수)', 'unit': '심볼',
     'path': ['latency', 'ours', 'tti_sym'], 'min': 1, 'max': 14, 'step': 1,
     'step_of': ['latency', 'ours'], 'hint': '14 면 슬롯 전체. 2 가 mini-slot'},
    {'id': 'lat_bler', 'item': 'lat', 'label': '1차 전송 오류율 (BLER)', 'unit': '',
     'path': ['latency', 'ours', 'bler'], 'min': 0.001, 'max': 0.2, 'step': 0.001,
     'step_of': ['latency', 'ours'], 'hint': '기준은 0.10'},
    {'id': 'rate_bw', 'item': 'rate', 'label': '사용자가 받는 대역폭', 'unit': 'MHz',
     'path': ['rate', 'ours', 'bw_hz'], 'min': 20, 'max': 200, 'step': 10, 'scale': 1e6,
     'step_of': ['rate', 'ours'], 'hint': 'Macro 기준은 20 MHz'},
    {'id': 'rate_users', 'item': 'rate', 'label': '동시 스케줄 사용자 수', 'unit': '명',
     'path': ['rate', 'ours', 'users'], 'min': 1, 'max': 10, 'step': 1,
     'step_of': ['rate', 'ours'], 'hint': '적을수록 한 사용자 몫이 커진다'},
    {'id': 'en_load', 'item': 'ee', 'label': 'SBS 평균 부하율', 'unit': '',
     'path': ['energy', 'sbs', 'load'], 'min': 0.2, 'max': 1.0, 'step': 0.01,
     'basis': None, 'hint': '이 지표가 가정에 가장 민감하다. 목표 30배의 경계가 여기서 갈린다'},
    {'id': 'en_nsbs', 'item': 'ee', 'label': 'SBS 개수', 'unit': '대',
     'path': ['energy', 'n_sbs'], 'min': 1, 'max': 12, 'step': 1, 'hint': '기준은 6대',
     'basis_text': 'MBS 한 대가 커버하던 영역을 SBS 몇 대가 나눠 맡는가. 많을수록 공간 재사용으로 처리량이 늘고 SBS 전력도 그만큼 는다.'},
    {'id': 'en_sleep', 'item': 'ee', 'label': 'MBS 절전 후 잔존 비율', 'unit': '',
     'path': ['energy', 'macro', 'sleep_residual'], 'min': 0.05, 'max': 1.0, 'step': 0.05,
     'hint': '1.0 이면 절전 없음'},
    {'id': 'en_avgse', 'item': 'ee', 'label': '피크 대비 평균 스펙트럼 효율', 'unit': '',
     'path': ['energy', 'avg_se_factor'], 'min': 0.1, 'max': 0.6, 'step': 0.01,
     'hint': '평균 처리량 환산 계수'},
    {'id': 'en_bh', 'item': 'ee', 'label': '백홀 전력 원단위', 'unit': 'W/(Gb/s)',
     'path': ['energy', 'backhaul_w_per_gbps'], 'min': 1, 'max': 30, 'step': 1,
     'hint': '캐시 히트분은 이 전력이 안 든다'},
    {'id': 'hit', 'item': 'ee', 'label': '캐시 히트율', 'unit': '%',
     'path': ['inputs', 'cache_hit', 'value_pct'], 'min': 0, 'max': 95, 'step': 0.25,
     'hint': '데모가 낸 값(62.25%)이 기본이다. 에너지 효율과 체감 속도에 들어간다'},
]


def _get(obj, path):
    for p in path:
        obj = obj[p]
    return obj


def _set(obj, path, value):
    for p in path[:-1]:
        obj = obj[p]
    obj[path[-1]] = value


class Model:
    """원본 가정과 입력을 들고 있다가 슬라이더 값을 덮어써서 다시 계산한다."""

    def __init__(self, assumptions_path, inputs_path):
        self.paths = (assumptions_path, inputs_path)
        self.a0 = evaluate.load(assumptions_path)
        self.m0 = evaluate.load(inputs_path)

    def _root(self, a, m, path):
        return (m, path[1:]) if path[0] == 'inputs' else (a, path)

    def knobs(self):
        out = []
        for k in KNOBS:
            root, path = self._root(self.a0, self.m0, k['path'])
            try:
                val = _get(root, path)
            except (KeyError, IndexError, TypeError):
                continue
            d = {x: k[x] for x in ('id', 'item', 'label', 'unit', 'min', 'max', 'step', 'hint')}
            sc = k.get('scale', 1)
            d['scale'] = sc
            d['default'] = val / sc
            basis = k.get('basis_text', '')
            if basis:
                pass
            elif k.get('step_of'):
                node = _get(self.a0, k['step_of'])
                basis = node.get('basis', '') if isinstance(node, dict) else ''
            elif k['id'] == 'en_load':
                basis = self.a0['energy']['sbs'].get('load_basis', '')
            elif k['id'] == 'en_sleep':
                basis = self.a0['energy']['macro'].get('sleep_basis', '')
            elif k['id'] == 'en_avgse':
                basis = self.a0['energy'].get('avg_se_basis', '')
            elif k['id'] == 'en_bh':
                basis = self.a0['energy'].get('backhaul_basis', '')
            elif k['id'] == 'hit':
                basis = ('콘텐츠 캐싱 태스크의 재생 결과. ' +
                         (self.m0.get('cache_hit', {}).get('source', '')))
            d['basis'] = basis
            out.append(d)
        return out

    def compute(self, values=None):
        a = copy.deepcopy(self.a0)
        m = copy.deepcopy(self.m0)
        changed = []
        by_id = {k['id']: k for k in KNOBS}
        for kid, v in (values or {}).items():
            k = by_id.get(kid)
            if not k:
                raise KeyError('모르는 슬라이더: %s' % kid)
            v = float(v)
            if not (k['min'] - 1e-9 <= v <= k['max'] + 1e-9):
                raise ValueError('%s 범위는 %g ~ %g' % (k['label'], k['min'], k['max']))
            root, path = self._root(a, m, k['path'])
            real = v * k.get('scale', 1)
            old = _get(root, path)
            if k['id'] in ('lat_sym', 'rate_users', 'en_nsbs', 'dl_bits', 'dl_ce', 'ul_ce'):
                real = int(round(real))
            if abs(old - real) > 1e-12:
                changed.append(kid)
            _set(root, path, real)
        res = evaluate.compute(a, m, {'assumptions': self.paths[0], 'inputs': self.paths[1]})
        res['changed'] = changed
        # 에너지 효율을 SBS 부하율에 대해 그리기 위한 곡선
        ee = next(i for i in res['items'] if i['id'] == 'ee')
        dl = next(i for i in res['items'] if i['id'] == 'se_dl')
        se_base, se_ours = dl['detail']['steps'][0]['value'], dl['value']
        hit = ee['detail']['hit_ratio']
        res['energy_curve'] = [
            {'load': round(l / 100.0, 2),
             'ratio': radio.energy_ratio(a['energy'], se_base, se_ours, hit, l / 100.0)}
            for l in range(10, 101, 2)]
        res.pop('assumptions', None)
        return res


class Handler(BaseHTTPRequestHandler):
    protocol_version = 'HTTP/1.1'
    model = None

    def log_message(self, *a):
        pass

    def _send(self, code, body, ctype):
        self.send_response(code)
        self.send_header('Content-Type', ctype)
        self.send_header('Content-Length', str(len(body)))
        self.send_header('Cache-Control', 'no-store')
        self.end_headers()
        self.wfile.write(body)

    def _json(self, obj, code=200):
        self._send(code, json.dumps(obj, ensure_ascii=False).encode('utf-8'),
                   'application/json; charset=utf-8')

    def do_GET(self):
        path = urlparse(self.path).path
        try:
            if path in ('/', '/index.html'):
                with open(os.path.join(WEB, 'index.html'), 'rb') as f:
                    return self._send(200, f.read(), 'text/html; charset=utf-8')
            if path == '/api/knobs':
                return self._json(self.model.knobs())
            if path == '/api/result':
                return self._json(self.model.compute())
            if path == '/api/simin/format':
                return self._json(simin.format_info())
            if path == '/api/simin/sample':
                return self._send(200, simin.sample_csv(self.model.a0, self.model.m0).encode('utf-8'),
                                  'text/csv; charset=utf-8')
            if path == '/api/info':
                return self._json({
                    'targets': {k: v for k, v in targets.BY_ID.items()},
                    'formulas': {k: list(v) for k, v in targets.FORMULAS.items()}})
        except Exception as ex:                                  # noqa: BLE001
            return self._json({'ok': False, 'error': str(ex)}, 500)
        self._json({'ok': False, 'error': 'not found'}, 404)

    def do_POST(self):
        try:
            n = int(self.headers.get('Content-Length', 0))
            d = json.loads(self.rfile.read(n).decode('utf-8')) if n else {}
            if self.path == '/api/simin/rows':
                return self._json(simin.rows_from(d.get('text', '')))
            if self.path == '/api/simin':
                return self._json(simin.evaluate(d.get('text', '')))
            if self.path == '/api/evaluate':
                return self._json(self.model.compute(d.get('values')))
        except (KeyError, ValueError) as ex:
            return self._json({'ok': False, 'error': str(ex)}, 400)
        except Exception as ex:                                  # noqa: BLE001
            return self._json({'ok': False, 'error': '%s: %s' % (type(ex).__name__, ex)}, 500)
        self._json({'ok': False, 'error': 'not found'}, 404)


def serve(assumptions_path, inputs_path, host='127.0.0.1', port=8810, ready=None):
    Handler.model = Model(assumptions_path, inputs_path)
    httpd = ThreadingHTTPServer((host, port), Handler)
    httpd.daemon_threads = True
    if ready:
        ready(httpd)
    try:
        httpd.serve_forever()
    finally:
        httpd.server_close()
