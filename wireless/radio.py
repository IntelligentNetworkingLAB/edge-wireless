# 평가 산식. 산식은 이 파일에만 있고 가정값은 config/assumptions.json 에서 읽는다.
# 표준 라이브러리만 사용한다.

SYM_PER_SLOT = 14          # NR 슬롯당 OFDM 심볼
RE_PER_SYM = 12            # RB 당 서브캐리어

LINK_KEYS = ('n_rb', 'scs_hz', 'slot_ms', 'ctrl_sym', 'ce_re',
             'bits_per_sym', 'code_rate', 'mimo_gain')


def payload_bits(c):
    """Payload = [(symbols - control) x 12 - CE overhead]
                 x bits/symbol x RB x coding x MIMO gain"""
    re_per_rb = (SYM_PER_SLOT - c['ctrl_sym']) * RE_PER_SYM - c['ce_re']
    if re_per_rb <= 0:
        raise ValueError('오버헤드가 슬롯 전체를 먹었다. ctrl_sym / ce_re 확인')
    return (re_per_rb * c['bits_per_sym'] * c['n_rb']
            * c['code_rate'] * c['mimo_gain'])


def throughput_bps(c):
    """Peak User Experienced Throughput = Payload / Timeslot duration"""
    return payload_bits(c) / (c['slot_ms'] * 1e-3)


def channel_bw_hz(c):
    return RE_PER_SYM * c['n_rb'] * c['scs_hz']


def spectral_eff(c):
    """Peak Spectral Efficiency = Throughput / (12 x RB x subcarrier BW)"""
    return throughput_bps(c) / channel_bw_hz(c)


def apply(cfg, changes):
    out = dict(cfg)
    for k, v in changes.items():
        if k not in LINK_KEYS:
            raise KeyError('모르는 링크 파라미터: %s' % k)
        out[k] = v
    return out


def waterfall(base, steps):
    """기준 설정에서 한 단계씩 바꿔 가며 스펙트럼 효율을 다시 계산한다.

    각 모듈이 기여하는 몫을 단계별로 나눠서 보여준다.
    """
    cur = base
    prev = spectral_eff(base)
    rows = [{'label': base.get('name', '기준 설정'), 'module': '',
             'basis': base.get('basis', ''), 'value': prev, 'factor': 1.0,
             'changed': {}, 'cfg': base}]
    for s in steps:
        changes = s.get('set', {})
        before = {k: cur[k] for k in changes}
        cur = apply(cur, changes)
        v = spectral_eff(cur)
        rows.append({'label': s['label'], 'module': s.get('module', ''),
                     'basis': s.get('basis', ''), 'value': v,
                     'factor': v / prev,
                     'changed': {k: (before[k], changes[k]) for k in changes},
                     'cfg': cur})
        prev = v
    return rows


# ------------------------------------------------------------------ Latency

def latency_parts(c):
    """산식은 Payload / Throughput 이고 Throughput 은 Payload / TTI 이므로
    결과는 TTI 와 같다. 즉 무선 구간 전송 단위 시간이다.

    정렬 지연과 재전송은 산식에 없지만 참고용으로 함께 계산한다.
    """
    tti = c['slot_ms'] * c['tti_sym'] / SYM_PER_SLOT
    align = tti / 2.0                            # 평균 스케줄링 정렬 지연
    harq = c['bler'] * (tti + align)             # 재전송 1회 기대값
    return {'tti': tti, 'align': align, 'harq': harq,
            'total': tti + align + harq}


# ---------------------------------------------------------------- Data Rate

def user_rate_bps(s):
    """사용자 속도 = 스펙트럼 효율 x 할당 대역폭 / 동시 스케줄 사용자 수"""
    return s['se'] * s['bw_hz'] / s['users']


def delivered_rate_bps(air_bps, backhaul_bps, hit_ratio):
    """캐시 히트는 공중 구간 속도로, 미스는 백홀 속도로 전달된다고 보고 조화 평균을 낸다.

    목표는 피크값 기준이며, 이 값은 캐싱이 체감 속도에 주는 영향을 따로 볼 때 쓴다.
    """
    miss = min(air_bps, backhaul_bps)
    return 1.0 / (hit_ratio / air_bps + (1.0 - hit_ratio) / miss)


# ------------------------------------------------------------ Energy

def power_in(model, p_out_w):
    """선형 전력 모델 P_in = P0 + dp x P_out."""
    return model['p0_w'] + model['dp'] * p_out_w


def energy_baseline(e, se_base):
    tp = e['avg_se_factor'] * se_base * e['macro']['bw_hz']
    p_rf = power_in(e['macro'], e['macro']['p_out_w'])
    p_bh = e['backhaul_w_per_gbps'] * tp / 1e9
    return {'tp_bps': tp, 'p_rf_w': p_rf, 'p_backhaul_w': p_bh,
            'p_total_w': p_rf + p_bh, 'ee_bps_w': tp / (p_rf + p_bh)}


def energy_ours(e, se_base, se_ours, hit_ratio, load=None):
    load = e['sbs']['load'] if load is None else load
    sbs_tp = (e['n_sbs'] * e['avg_se_factor'] * se_ours
              * e['sbs']['bw_hz'] * load)
    mbs_tp = (e['avg_se_factor'] * se_base * e['macro']['bw_hz']
              * e['macro']['sleep_residual'])
    tp = sbs_tp + mbs_tp
    p_mbs = power_in(e['macro'],
                     e['macro']['p_out_w'] * e['macro']['sleep_residual'])
    p_sbs = e['n_sbs'] * power_in(e['sbs'], e['sbs']['p_out_w'])
    # 캐시에서 바로 나가는 트래픽은 백홀을 타지 않는다
    p_bh = e['backhaul_w_per_gbps'] * (tp / 1e9) * (1.0 - hit_ratio)
    total = p_mbs + p_sbs + p_bh
    return {'tp_bps': tp, 'sbs_tp_bps': sbs_tp, 'mbs_tp_bps': mbs_tp,
            'p_mbs_w': p_mbs, 'p_sbs_w': p_sbs, 'p_backhaul_w': p_bh,
            'p_total_w': total, 'ee_bps_w': tp / total, 'load': load}


def energy_ratio(e, se_base, se_ours, hit_ratio, load=None):
    return (energy_ours(e, se_base, se_ours, hit_ratio, load)['ee_bps_w']
            / energy_baseline(e, se_base)['ee_bps_w'])


def energy_crossover_load(e, se_base, se_ours, hit_ratio, want):
    """목표 배수를 만족하는 최소 SBS 부하율.

    5개 항목 중 가정에 가장 민감한 지표라서 임계값을 따로 계산한다.
    """
    if energy_ratio(e, se_base, se_ours, hit_ratio, 1.0) < want:
        return None
    lo, hi = 1e-3, 1.0
    for _ in range(60):
        mid = (lo + hi) / 2
        if energy_ratio(e, se_base, se_ours, hit_ratio, mid) < want:
            lo = mid
        else:
            hi = mid
    return hi
