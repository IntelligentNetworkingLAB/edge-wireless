# 보고서 렌더러. 계산은 evaluate.py 에서 끝나고 여기서는 표시만 한다.
#
# 콘솔, 마크다운, 단독 HTML 세 가지. HTML 은 외부 파일을 참조하지 않는 한 장짜리 문서다.

import html as _html
import os
import textwrap
import time
import unicodedata

from . import radio, targets

W = 88


def dw(s):
    """한글은 터미널에서 두 칸을 차지한다. 표가 어긋나지 않게 폭을 따로 센다."""
    return sum(2 if unicodedata.east_asian_width(c) in 'WF' else 1
               for c in str(s))


def pad(s, n, right=False):
    s = str(s)
    fill = ' ' * max(0, n - dw(s))
    return fill + s if right else s + fill


def wrap(text, indent='    '):
    if not text:
        return ''
    return textwrap.fill(str(text), width=W, initial_indent=indent,
                         subsequent_indent=indent)


def num(tid, v):
    if v is None:
        return '—'
    if tid == 'lat':
        return '%.4f' % v
    if tid == 'rate':
        return '%.1f' % v
    return '%.2f' % v


def mark(ok):
    return '—' if ok is None else ('충족' if ok else '미달')


def si(bps):
    if bps >= 1e9:
        return '%.3f Gb/s' % (bps / 1e9)
    if bps >= 1e6:
        return '%.1f Mb/s' % (bps / 1e6)
    return '%.0f b/s' % bps


# ==================================================================== 콘솔

def _head(out, txt, ch='='):
    out.append('')
    out.append(ch * W)
    out.append(' ' + txt)
    out.append(ch * W)


def _sub(out, txt):
    out.append('')
    out.append(txt)
    out.append('-' * W)


def _formula(out, pairs, note=''):
    out.append('  산식')
    for name, expr in pairs:
        out.append('    %s' % name)
        out.append(textwrap.fill(expr, width=W, initial_indent='      = ',
                                 subsequent_indent='        '))
    if note:
        out.append(wrap('* ' + note, '    '))


def _spectral(out, it, n):
    d = it['detail']
    _sub(out, '%s %s' % (n, it['label']))
    _formula(out, d['formula'])
    s, c = d['base_substitution'], d['base_cfg']
    out.append('')
    out.append('  기준 설정 대입')
    out.append('    RB 당 RE = (14 - %g) x 12 - %g = %g'
               % (c['ctrl_sym'], c['ce_re'], s['re_per_rb']))
    out.append('    Payload  = %g x %g x %d x %.3f x %g = %s bits'
               % (s['re_per_rb'], c['bits_per_sym'], c['n_rb'],
                  c['code_rate'], c['mimo_gain'],
                  format(int(s['payload_bits']), ',')))
    out.append('    Throughput = %s bits / %.3f ms = %s'
               % (format(int(s['payload_bits']), ','), c['slot_ms'],
                  si(s['throughput_bps'])))
    out.append('    SE = %s / (12 x %d x %.0f kHz = %.2f MHz) = %.2f %s'
               % (si(s['throughput_bps']), c['n_rb'], c['scs_hz'] / 1e3,
                  s['channel_bw_hz'] / 1e6, s['value'], it['unit']))
    out.append(wrap('근거: ' + c.get('basis', ''), '    '))
    out.append('')
    out.append('  단계별 기여')
    out.append('    %s %s %s  %s' % (pad('단계', 28), pad(it['unit'], 9, True),
                                     pad('배수', 8, True), '담당 모듈'))
    for r in d['steps']:
        out.append('    %s %s %s  %s'
                   % (pad(r['label'], 28), pad('%.2f' % r['value'], 9, True),
                      pad('—' if r['factor'] == 1.0
                          else 'x%.3f' % r['factor'], 8, True),
                      r['module'] or '—'))
    for r in d['steps'][1:]:
        chg = ', '.join('%s %g→%g' % (k, a, b)
                        for k, (a, b) in r['changed'].items())
        out.append('')
        out.append(wrap('[%s] %s' % (r['label'], chg), '    '))
        out.append(wrap(r['basis'], '      '))


def _latency(out, it, n):
    d = it['detail']
    _sub(out, '%s %s' % (n, it['label']))
    _formula(out, d['formula'])
    out.append(wrap(d['note'], '    '))
    out.append('')
    out.append('    %s %s %s' % (pad('항목 (ms)', 26), pad('기준', 11, True),
                                 pad('제안', 11, True)))
    for k, lab in (('tti', 'TTI (산식값)'), ('align', '스케줄링 정렬'),
                   ('harq', 'HARQ 재전송 기대'), ('total', '합계')):
        out.append('    %s %s %s' % (pad(lab, 26),
                                     pad('%.4f' % d['base'][k], 11, True),
                                     pad('%.4f' % d['ours'][k], 11, True)))
    out.append('')
    out.append(wrap('기준: ' + d['base_cfg'].get('basis', ''), '    '))
    out.append(wrap('제안: ' + d['ours_cfg'].get('basis', ''), '    '))
    if d.get('caveat'):
        out.append('')
        out.append(wrap('주의: ' + d['caveat'], '    '))


def _rate(out, it, n):
    d = it['detail']
    _sub(out, '%s %s' % (n, it['label']))
    _formula(out, d['formula'], d.get('formula_note', ''))
    for side in ('base', 'ours'):
        s = d[side]
        out.append('')
        out.append('    %s' % s['name'])
        out.append('      %.2f b/s/Hz x %.0f MHz / %g명 = %s'
                   % (s['se'], s['bw_hz'] / 1e6, s['users'], si(s['value_bps'])))
        out.append(wrap(s.get('basis', ''), '      '))
    out.append(wrap(d['note'], '    '))
    dv = d.get('delivered')
    if dv:
        h = dv['hit']
        out.append('')
        out.append('  참고: 캐시를 반영한 체감 평균 (백홀 %s 가정)'
                   % si(dv['backhaul_bps']))
        out.append('    히트율 %.2f%% (학습) -> %s'
                   % (h['value_pct'], si(dv['ours_bps'])))
        out.append('    히트율 %.2f%% (%s) -> %s   차이 %+.1f%%'
                   % (h['baseline_pct'], h.get('baseline_name', '비교군'),
                      si(dv['base_bps']),
                      100 * (dv['ours_bps'] / dv['base_bps'] - 1)))
        out.append(wrap('출처: ' + h.get('source', ''), '    '))


def _energy(out, it, n):
    d = it['detail']
    _sub(out, '%s %s' % (n, it['label']))
    _formula(out, d['formula'], d.get('formula_note', ''))
    out.append(wrap('근거: ' + d['basis'], '    '))
    b, o = d['baseline'], d['ours']
    out.append('')
    out.append('  기준 (MBS 단독)')
    out.append('    처리량 %s / 전력 %.1f W (RF %.1f + 백홀 %.2f)'
               % (si(b['tp_bps']), b['p_total_w'], b['p_rf_w'],
                  b['p_backhaul_w']))
    out.append('    EE = %.4f Mb/s/W' % (b['ee_bps_w'] / 1e6))
    out.append('')
    out.append('  제안 (MBS 절전 + SBS 밀집, 부하율 %.2f)' % o['load'])
    out.append('    처리량 %s / 전력 %.1f W (MBS %.1f + SBS %.1f + 백홀 %.1f)'
               % (si(o['tp_bps']), o['p_total_w'], o['p_mbs_w'], o['p_sbs_w'],
                  o['p_backhaul_w']))
    out.append('    EE = %.4f Mb/s/W' % (o['ee_bps_w'] / 1e6))
    out.append('')
    out.append('  개선 배수 = %.4f / %.4f = %.2f배'
               % (o['ee_bps_w'] / 1e6, b['ee_bps_w'] / 1e6, it['value']))
    out.append(wrap(d['note'] + ' (스펙트럼 효율 기여분 x%.2f)' % d['se_gain'],
                    '    '))
    out.append('')
    out.append('  민감도 - SBS 부하율')
    for s in d['sweep']:
        out.append('    %s %s  %s'
                   % (pad('%.2f' % s['load'], 8, True),
                      pad('%.2f배' % s['ratio'], 10, True),
                      '' if s['ratio'] >= it['target'] else '목표 미달'))
    if d['crossover_load'] is not None:
        out.append('    목표 %g배를 만족하는 최소 부하율 %.3f'
                   % (it['target'], d['crossover_load']))
        out.append(wrap('5개 항목 중 이 지표가 가정에 가장 민감하다.', '    '))


def text(res):
    out = []
    _head(out, '무선 구간 성능 평가')
    out.append(' 생성 %s' % time.strftime('%Y-%m-%d %H:%M:%S'))
    out.append(' 가정 %s' % res['sources']['assumptions'])
    out.append(' 입력 %s' % res['sources']['inputs'])
    out.append('')
    out.append(' [근거 등급]')
    out.append('   산식  산식에 선언한 가정을 넣어 계산한 값. 장비 측정값이 아니다')
    out.append('   인용  외부 실적에서 가져온 값')
    out.append('   없음  입력이 없어 측정하지 못함')

    _head(out, '1. 종합', '=')
    out.append('  %s %s %s %s %s'
               % (pad('항목', 32), pad('기준 수준', 9, True),
                  pad('목표', 9, True),
                  pad('산출값', 12, True), pad('근거/판정', 11, True)))
    out.append('  ' + '-' * (W - 2))
    for it in res['items']:
        out.append('  %s %s %s %s %s'
                   % (pad(it['label'], 32),
                      pad(num(it['id'], it['ref']), 9, True),
                      pad(num(it['id'], it['target']), 9, True),
                      pad(num(it['id'], it['value']) +
                          (' ' + it['unit'] if it['unit'] else ''), 12, True),
                      pad('%s/%s' % (it['grade_label'], mark(it['ok'])),
                          11, True)))
    out.append('')
    out.append('  충족 %d / 전체 %d 항목'
               % (res['passed'], res['total']))

    _head(out, '2. 항목별 산출', '=')
    fn = {'se_dl': _spectral, 'se_ul': _spectral, 'ee': _energy,
          'rate': _rate, 'lat': _latency}
    for i, it in enumerate(res['items'], 1):
        fn[it['id']](out, it, '2.%d' % i)

    _head(out, '3. 확인할 것', '=')
    if not res['warnings']:
        out.append('  없음.')
    for w in res['warnings']:
        out.append(wrap('- ' + w, '  '))
    out.append('')
    out.append(wrap('근거 등급이 산식인 항목은 계산값이며 장비 측정값이 아니다. '
                    '가정을 바꾸면 값이 바뀌고, 가정은 assumptions.json 에 '
                    '근거와 함께 적혀 있다.', '  '))
    out.append('')
    return '\n'.join(out)


# ================================================================ 마크다운

def markdown(res):
    L = ['# 무선 구간 성능 평가', '',
         '무선 구간 5개 항목을 산식으로 산출한 결과.', '',
         '- 생성 %s' % time.strftime('%Y-%m-%d %H:%M:%S'),
         '- 가정 `%s`' % res['sources']['assumptions'],
         '- 입력 `%s`' % res['sources']['inputs'],
         '- 이 파일은 `run.py` 출력본이다. 손으로 고치지 말고 다시 돌릴 것.',
         '', '## 종합', '',
         '| 항목 | 기준 수준 | 목표 | 산출값 | 근거 | 판정 |',
         '|---|---|---|---|---|---|']
    for it in res['items']:
        L.append('| %s | %s (%s) | %s | **%s** %s | %s | %s |'
                 % (it['label'], num(it['id'], it['ref']), it['ref_src'],
                    num(it['id'], it['target']), num(it['id'], it['value']),
                    it['unit'], it['grade_label'], mark(it['ok'])))
    L += ['', '충족 **%d** / 전체 %d 항목.'
          % (res['passed'], res['total']), '']
    if res['warnings']:
        L += ['### 확인할 것', '']
        L += ['- ' + w for w in res['warnings']]
        L.append('')
    L += ['## 단계별 기여', '']
    for tid in ('se_dl', 'se_ul'):
        it = next(x for x in res['items'] if x['id'] == tid)
        L += ['### %s' % it['label'], '',
              '| 단계 | %s | 배수 | 담당 모듈 |' % it['unit'], '|---|---|---|---|']
        for r in it['detail']['steps']:
            L.append('| %s | %.2f | %s | %s |'
                     % (r['label'], r['value'],
                        '—' if r['factor'] == 1.0 else '×%.3f' % r['factor'],
                        r['module'] or '—'))
        L.append('')
        for r in it['detail']['steps'][1:]:
            L.append('- **%s** — %s' % (r['label'], r['basis']))
        L.append('')
    L += ['## 전체 출력', '', '```', text(res), '```', '']
    return '\n'.join(L)


# ==================================================================== HTML

CSS = """
:root{--bg:#eef1f6;--panel:#fff;--surface:#f7f9fc;--line:#dde3ec;--line2:#c8d1de;
--ink:#16202e;--ink2:#55637a;--ink3:#8b98ab;--head:#0d2c54;--blue:#1f5fa8;
--blue-lt:#eaf1fa;--green:#15754f;--green-lt:#e7f3ed;--amber:#96690f;
--amber-lt:#fbf2e0;--red:#ad3a30;--red-lt:#faedec;--violet:#574c8c;
--violet-lt:#eeecf7;--mono:Consolas,"D2Coding",Menlo,monospace}
@media(prefers-color-scheme:dark){:root:not([data-theme=light]){
--bg:#161a21;--panel:#1d222b;--surface:#222834;--line:#2c3440;--line2:#3a4453;
--ink:#e4e9f0;--ink2:#a8b3c4;--ink3:#7a8699;--head:#cfe0f5;--blue:#6ba3e8;
--blue-lt:#1d2c40;--green:#5bbd8f;--green-lt:#16302a;--amber:#d4a53f;
--amber-lt:#332a16;--red:#e0796d;--red-lt:#331f1e;--violet:#a79ddc;
--violet-lt:#262240}}
*{box-sizing:border-box}
body{margin:0;background:var(--bg);color:var(--ink);
font:13px/1.55 -apple-system,"Segoe UI","Malgun Gothic",sans-serif}
.wrap{max-width:1140px;margin:0 auto;padding:0 16px 56px}
header{padding:20px 0 13px;border-bottom:2px solid var(--head);margin-bottom:18px}
h1{margin:0;font-size:19px;color:var(--head);letter-spacing:-.3px}
header p{margin:5px 0 0;font-size:11px;color:var(--ink3)}
h2{font-size:14px;color:var(--head);margin:30px 0 10px;padding-bottom:6px;
border-bottom:1px solid var(--line2)}
h3{font-size:12.5px;margin:20px 0 7px;color:var(--ink)}
h3 em{font-style:normal;font-family:var(--mono);font-size:11px;color:var(--ink3);
margin-left:8px}
table{width:100%;border-collapse:collapse;background:var(--panel);
border:1px solid var(--line);margin:8px 0}
th,td{padding:7px 10px;text-align:left;border-bottom:1px solid var(--line);
font-size:11.5px;vertical-align:top}
th{background:var(--surface);color:var(--ink3);font-size:10px;white-space:nowrap}
tr:last-child td{border-bottom:none}
td.n,th.n{text-align:right;font-family:var(--mono);white-space:nowrap}
td.big{font-size:15px;font-weight:700;color:var(--head)}
.tag{display:inline-block;font-size:9.5px;padding:2px 6px;
border:1px solid var(--line2);color:var(--ink3);background:var(--surface)}
.tag.calc{border-color:var(--amber);color:var(--amber);background:var(--amber-lt)}
.tag.meas{border-color:var(--green);color:var(--green);background:var(--green-lt)}
.tag.cite{border-color:var(--violet);color:var(--violet);background:var(--violet-lt)}
.ok{color:var(--green);font-weight:700}.no{color:var(--red);font-weight:700}
.why{font-size:11px;color:var(--ink2);margin:4px 0}
.mod{font-size:10px;color:var(--blue);font-family:var(--mono)}
.f{font-family:var(--mono);font-size:11px;background:var(--surface);
border-left:3px solid var(--line2);padding:7px 11px;margin:6px 0;
color:var(--ink2);overflow-x:auto}
.note{border-left:3px solid var(--amber);background:var(--amber-lt);
padding:10px 13px;font-size:11.5px;margin:12px 0;color:var(--ink2)}
.note.bad{border-left-color:var(--red);background:var(--red-lt)}
.bar{display:inline-block;height:9px;background:var(--blue);min-width:1px;
vertical-align:middle}
.bar.over{background:var(--green)}.bar.under{background:var(--red)}
@media(max-width:760px){th,td{padding:6px}.wrap{padding:0 12px 40px}table{display:block;overflow-x:auto}}
@media print{body{background:#fff}.note{break-inside:avoid}}
"""


def _e(s):
    return _html.escape(str(s if s is not None else ''))


def _h_summary(res):
    rows = []
    for it in res['items']:
        ok = ('<td>—</td>' if it['ok'] is None else
              '<td class="%s">%s</td>' % ('ok' if it['ok'] else 'no',
                                          mark(it['ok'])))
        rows.append(
            '<tr><td><b>%s</b></td><td class="n">%s<br><span class="why">%s</span></td>'
            '<td class="n">%s</td>'
            '<td class="n big">%s</td><td>%s</td>'
            '<td><span class="tag %s">%s</span></td>%s</tr>'
            % (_e(it['label']), num(it['id'], it['ref']), _e(it['ref_src']),
               num(it['id'], it['target']), num(it['id'], it['value']),
               _e(it['unit']), it['grade'], _e(it['grade_label']), ok))
    cite = ''
    warn = ''
    if res['warnings']:
        warn = ('<div class="note bad"><b>확인할 것</b><br>'
                + '<br>'.join('· ' + _e(w) for w in res['warnings'])
                + '</div>')
    return ('<h2>1. 종합</h2><table><thead><tr><th>항목</th>'
            '<th class="n">기준 수준</th>'
            '<th class="n">목표</th><th class="n">산출값</th>'
            '<th>단위</th><th>근거</th><th>판정</th></tr></thead>'
            '<tbody>%s</tbody></table>'
            '<p class="why">충족 <b>%d</b> / 전체 %d 항목. '
            '<span class="tag calc">산식</span> 산식에 선언한 가정을 넣어 '
            '계산한 값이다. 장비 측정값이 아니다.</p>%s%s'
            % (''.join(rows), res['passed'], res['total'],
               warn, cite))


def _h_formula(pairs, note=''):
    out = ''.join('<div class="f"><b>%s</b> = %s</div>' % (_e(a), _e(b))
                  for a, b in pairs)
    if note:
        out += '<p class="why">* %s</p>' % _e(note)
    return out


def _h_spectral(it):
    d = it['detail']
    mx = max([r['value'] for r in d['steps']] + [it['target']]) * 1.05
    rows = ''
    for r in d['steps']:
        w = 100.0 * r['value'] / mx
        cls = 'over' if r['value'] >= it['target'] else ''
        rows += ('<tr><td><b>%s</b>%s</td><td class="n">%.2f</td>'
                 '<td class="n">%s</td><td style="width:38%%">'
                 '<span class="bar %s" style="width:%.1f%%"></span></td></tr>'
                 % (_e(r['label']),
                    '<br><span class="mod">%s</span>' % _e(r['module'])
                    if r['module'] else '', r['value'],
                    '—' if r['factor'] == 1.0 else '×%.3f' % r['factor'],
                    cls, w))
        if r['basis']:
            rows += ('<tr><td colspan="4" class="why">%s</td></tr>'
                     % _e(r['basis']))
    s, c = d['base_substitution'], d['base_cfg']
    return ('<h3>%s <em>목표 %g %s</em></h3>%s'
            '<div class="f">기준 대입 · RB당 RE = (14 − %g)×12 − %g = %g · '
            'Payload = %s bits · Throughput = %s · SE = %.2f %s</div>'
            '<p class="why">%s</p>'
            '<table><thead><tr><th>단계 / 담당 모듈</th><th class="n">%s</th>'
            '<th class="n">배수</th><th></th></tr></thead><tbody>%s</tbody></table>'
            % (_e(it['label']), it['target'], _e(it['unit']),
               _h_formula(d['formula']), c['ctrl_sym'], c['ce_re'],
               s['re_per_rb'], format(int(s['payload_bits']), ','),
               si(s['throughput_bps']), s['value'], _e(it['unit']),
               _e(c.get('basis', '')), _e(it['unit']), rows))


def _h_latency(it):
    d = it['detail']
    rows = ''.join('<tr><td>%s</td><td class="n">%.4f</td>'
                   '<td class="n%s">%.4f</td></tr>'
                   % (lab, d['base'][k], ' big' if k == 'tti' else '',
                      d['ours'][k])
                   for k, lab in (('tti', 'TTI (산식값)'),
                                  ('align', '스케줄링 정렬'),
                                  ('harq', 'HARQ 재전송 기대'),
                                  ('total', '합계')))
    return ('<h3>%s <em>목표 %g ms</em></h3>%s<p class="why">%s</p>'
            '<table><thead><tr><th>항목 (ms)</th><th class="n">5G 기준</th>'
            '<th class="n">제안</th></tr></thead><tbody>%s</tbody></table>'
            '<p class="why"><b>기준:</b> %s</p>'
            '<p class="why"><b>제안:</b> %s</p>'
            '<div class="note">%s</div>'
            % (_e(it['label']), it['target'], _h_formula(d['formula']),
               _e(d['note']), rows, _e(d['base_cfg'].get('basis', '')),
               _e(d['ours_cfg'].get('basis', '')), _e(d.get('caveat', ''))))


def _h_rate(it):
    d = it['detail']
    rows = ''.join(
        '<tr><td><b>%s</b></td><td class="n%s">%s</td>'
        '<td class="why">%.2f b/s/Hz × %.0f MHz ÷ %g명<br>%s</td></tr>'
        % (_e(d[k]['name']), ' big' if k == 'ours' else '',
           si(d[k]['value_bps']), d[k]['se'], d[k]['bw_hz'] / 1e6,
           d[k]['users'], _e(d[k].get('basis', '')))
        for k in ('base', 'ours'))
    extra = ''
    dv = d.get('delivered')
    if dv:
        h = dv['hit']
        extra = ('<p class="why"><b>참고 — 캐시를 반영한 체감 평균</b> '
                 '(백홀 %s 가정). 히트율 %.2f%% → %s, %s %.2f%% → %s '
                 '(차이 %+.1f%%). 최대 Data Rate 보고값에는 들어가지 않는다.</p>'
                 % (si(dv['backhaul_bps']), h['value_pct'], si(dv['ours_bps']),
                    _e(h.get('baseline_name', '비교군')), h['baseline_pct'],
                    si(dv['base_bps']),
                    100 * (dv['ours_bps'] / dv['base_bps'] - 1)))
    return ('<h3>%s <em>목표 %g Mb/s</em></h3>%s<table><tbody>%s</tbody></table>'
            '<p class="why">%s</p>%s'
            % (_e(it['label']), it['target'],
               _h_formula(d['formula'], d.get('formula_note', '')), rows,
               _e(d['note']), extra))


def _h_energy(it):
    d = it['detail']
    b, o = d['baseline'], d['ours']
    sweep = ''.join(
        '<tr><td class="n">%.2f</td><td class="n">%.2f배</td>'
        '<td style="width:45%%"><span class="bar %s" style="width:%.1f%%">'
        '</span></td><td class="why">%s</td></tr>'
        % (s['load'], s['ratio'],
           'over' if s['ratio'] >= it['target'] else 'under',
           min(100.0, 100.0 * s['ratio'] / (it['target'] * 1.5)),
           '' if s['ratio'] >= it['target'] else '목표 미달')
        for s in d['sweep'])
    cross = ('없음' if d['crossover_load'] is None
             else '%.3f' % d['crossover_load'])
    return ('<h3>%s <em>목표 %g배</em></h3>%s<p class="why">%s</p>'
            '<table><tbody>'
            '<tr><td>기준 (MBS 단독)</td><td class="n">%s</td>'
            '<td class="n">%.1f W</td><td class="n">%.4f Mb/s/W</td></tr>'
            '<tr><td>제안 (MBS 절전 + SBS 밀집, 부하율 %.2f)</td>'
            '<td class="n">%s</td><td class="n">%.1f W</td>'
            '<td class="n">%.4f Mb/s/W</td></tr>'
            '<tr><td><b>개선 배수</b></td><td></td><td></td>'
            '<td class="n big">%.2f배</td></tr></tbody></table>'
            '<p class="why">%s (스펙트럼 효율 기여분 ×%.2f)</p>'
            '<h3>민감도 — SBS 부하율</h3>'
            '<table><thead><tr><th class="n">부하율</th>'
            '<th class="n">개선 배수</th><th></th><th></th></tr></thead>'
            '<tbody>%s</tbody></table>'
            '<div class="note">5개 항목 중 <b>이 지표가 가정에 가장 민감하다.</b> '
            '목표 %g배를 만족하는 최소 SBS 부하율은 <b>%s</b>, 기본 가정은 '
            '%.2f 다.</div>'
            % (_e(it['label']), it['target'],
               _h_formula(d['formula'], d.get('formula_note', '')),
               _e(d['basis']), si(b['tp_bps']), b['p_total_w'],
               b['ee_bps_w'] / 1e6, o['load'], si(o['tp_bps']), o['p_total_w'],
               o['ee_bps_w'] / 1e6, it['value'], _e(d['note']), d['se_gain'],
               sweep, it['target'], cross, o['load']))


def html(res):
    fn = {'se_dl': _h_spectral, 'se_ul': _h_spectral, 'ee': _h_energy,
          'rate': _h_rate, 'lat': _h_latency}
    body = ''.join(fn[it['id']](it) for it in res['items'])
    return ('<!DOCTYPE html>\n<html lang="ko"><head><meta charset="utf-8">'
            '<meta name="viewport" content="width=device-width,initial-scale=1">'
            '<title>무선 구간 성능 평가</title>'
            '<style>%s</style></head><body><div class="wrap">'
            '<header><h1>무선 구간 성능 평가</h1>'
            '<p>생성 %s</p>'
            '<p>가정 <code title="%s">%s</code> · 입력 <code title="%s">%s</code>'
            '</p></header>'
            '%s<h2>2. 항목별 산출</h2>%s'
            '</div></body></html>'
            % (CSS, time.strftime('%Y-%m-%d %H:%M:%S'),
               _e(res['sources']['assumptions']),
               _e(os.path.basename(res['sources']['assumptions'])),
               _e(res['sources']['inputs']),
               _e(os.path.basename(res['sources']['inputs'])),
               _h_summary(res), body))
