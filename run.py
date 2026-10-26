#!/usr/bin/env python3
# 무선 구간 성능 평가.
#
# 무선 구간 5개 항목(스펙트럼 효율 DL/UL, 에너지 효율, 사용자 Data Rate, Latency)을
# 산식으로 산출하고 목표 대비 판정한다.
# 표준 라이브러리만 사용한다.
#
#   python run.py                         콘솔 보고서
#   python run.py --html out/report.html  단독 HTML
#   python run.py --md out/report.md
#   python run.py --json out/result.json
#   python run.py --all                   세 가지 전부 out/ 에 저장
#   python run.py --check                 판정만 출력. 미달이면 종료 코드 1
#   python run.py --serve                 웹 인터페이스
#
#   python run.py -a assumptions.json -i inputs.json
#
# 가정은 config/assumptions.json, 외부 입력은 config/inputs.json 에 있다.

import argparse
import json
import os
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)

from wireless import evaluate, render                            # noqa: E402

DEF_A = os.path.join(HERE, 'config', 'assumptions.json')
DEF_I = os.path.join(HERE, 'config', 'inputs.json')
OUT = os.path.join(HERE, 'out')


def _utf8():
    for s in (sys.stdout, sys.stderr):
        try:
            s.reconfigure(encoding='utf-8')
        except Exception:
            pass


def save(path, body):
    d = os.path.dirname(os.path.abspath(path))
    if d:
        os.makedirs(d, exist_ok=True)
    with open(path, 'w', encoding='utf-8') as f:
        f.write(body)
    return path


def rel(p):
    try:
        return os.path.relpath(p, HERE)
    except ValueError:
        return p


def main(argv=None):
    _utf8()
    ap = argparse.ArgumentParser(
        description='무선 구간 성능 평가',
        formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument('-a', '--assumptions', default=DEF_A,
                    help='가정 파일 (기본 config/assumptions.json)')
    ap.add_argument('-i', '--inputs', default=DEF_I,
                    help='입력 파일 (기본 config/inputs.json)')
    ap.add_argument('--html', nargs='?', const=os.path.join(OUT, 'report.html'),
                    metavar='PATH', help='단독 HTML 보고서')
    ap.add_argument('--md', nargs='?', const=os.path.join(OUT, 'report.md'),
                    metavar='PATH', help='마크다운 보고서')
    ap.add_argument('--json', nargs='?', const=os.path.join(OUT, 'result.json'),
                    metavar='PATH', help='계산 결과 전체')
    ap.add_argument('--all', action='store_true', help='세 형식 전부 out/ 에')
    ap.add_argument('--quiet', action='store_true', help='콘솔 출력 생략')
    ap.add_argument('--serve', action='store_true',
                    help='웹 인터페이스. 가정을 슬라이더로 바꿔 보며 다시 계산한다')
    ap.add_argument('--host', default='127.0.0.1')
    ap.add_argument('--port', type=int, default=8810)
    ap.add_argument('--open', action='store_true', help='브라우저를 자동으로 연다')
    ap.add_argument('--check', action='store_true',
                    help='판정 요약만. 미달이 있으면 종료 코드 1')
    args = ap.parse_args(argv)

    for p in (args.assumptions, args.inputs):
        if not os.path.exists(p):
            ap.error('파일이 없다: %s' % p)

    if args.serve:
        from wireless import web
        url = 'http://%s:%d' % (args.host, args.port)
        print('웹 인터페이스 %s  (종료: Ctrl+C)' % url)
        if args.host not in ('127.0.0.1', 'localhost'):
            print('주의: 인증이 없다. 계산만 하고 파일을 바꾸지는 않지만 신뢰할 수 있는 망에서만 열 것.')
        if args.open:
            import webbrowser
            webbrowser.open(url)
        try:
            web.serve(args.assumptions, args.inputs, args.host, args.port)
        except KeyboardInterrupt:
            print('종료')
        return 0

    res = evaluate.run(args.assumptions, args.inputs)

    if args.check:
        for it in res['items']:
            print('%-34s %-7s %s' % (it['label'], it['grade_label'],
                                     render.mark(it['ok'])))
        print('충족 %d / 전체 %d'
              % (res['passed'], res['total']))
        for w in res['warnings']:
            print('! ' + w)
        return 0 if res['passed'] == res['total'] else 1

    if not args.quiet:
        print(render.text(res))

    wrote = []
    if args.all or args.html:
        wrote.append(save(args.html or os.path.join(OUT, 'report.html'),
                          render.html(res)))
    if args.all or args.md:
        wrote.append(save(args.md or os.path.join(OUT, 'report.md'),
                          render.markdown(res)))
    if args.all or args.json:
        wrote.append(save(args.json or os.path.join(OUT, 'result.json'),
                          json.dumps(res, ensure_ascii=False, indent=2)))
    for p in wrote:
        print('-> %s' % rel(p))

    return 0


if __name__ == '__main__':
    sys.exit(main())
