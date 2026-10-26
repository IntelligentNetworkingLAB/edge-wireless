# 무선 구간 평가 항목과 기준 수준, 목표.
#
# ref        기준 수준
# ref_src    그 수준의 출처
# target     목표치
# dir        up 이면 클수록 좋고 down 이면 작을수록 좋다
# kind       radio 는 무선 구간 산식

ITEMS = [
    {
        'id': 'se_dl', 'kind': 'radio', 'dir': 'up',
        'label': 'Downlink 스펙트럼 최대 효율', 'unit': 'b/s/Hz',
        'ref': 20.0, 'ref_src': '5G 표준',
        'target': 30.0,
    },
    {
        'id': 'se_ul', 'kind': 'radio', 'dir': 'up',
        'label': 'Uplink 스펙트럼 최대 효율', 'unit': 'b/s/Hz',
        'ref': 20.0, 'ref_src': '5G 표준',
        'target': 30.0,
    },
    {
        'id': 'ee', 'kind': 'radio', 'dir': 'up',
        'label': '네트워크 에너지 효율', 'unit': '배',
        'ref': 1.0, 'ref_src': '기준값',
        'target': 30.0,
        'note': 'SBS 기반',
    },
    {
        'id': 'rate', 'kind': 'radio', 'dir': 'up',
        'label': '사용자 측면에서의 최대 Data Rate', 'unit': 'Mb/s',
        'ref': 100.0, 'ref_src': 'Macro Cell 기반, 5G 표준',
        'target': 1000.0,
    },
    {
        'id': 'lat', 'kind': 'radio', 'dir': 'down',
        'label': '사용자 측면에서의 최소 Latency', 'unit': 'ms',
        'ref': 1.0, 'ref_src': '5G 표준',
        'target': 0.1,
    },
]

BY_ID = {x['id']: x for x in ITEMS}

# 평가 산식. 화면과 보고서에 그대로 표시한다.
FORMULAS = {
    'se': ('Peak Spectral Efficiency (b/s/Hz)',
           'Peak User Experienced Throughput / (12 x No.of RB x subcarrier BW)'),
    'tp': ('Peak User Experienced Throughput (kb/s)',
           'Payload (bits) / Timeslot duration (ms)'),
    'payload': ('Data Packet or Payload',
                '[(symbols/subcarrier - control overhead) x 12 '
                '- channel estimation overhead] x bits/symbol x No.of RB '
                'x coding x MIMO gain'),
    'lat': ('Latency (ms)',
            'Payload (bits) / Peak User Experienced Throughput (kb/s)'),
    'ee': ('Network Energy Efficiency (bits/s/watt)',
           'Peak User Experienced Throughput (bits/s) / Total Energy Consumed (watt)'),
}

