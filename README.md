# Edge Wireless — Wireless Link KPI Calculator

Computes five wireless-link KPIs from simulation outputs (payload, throughput, power, latency, ...) and compares them against target levels. Every result comes with its calculation steps, and the assumptions behind each value are kept in a config file. Standard library only (Python 3.10+).

| KPI | Formula | Reference | Target |
|---|---|---|---|
| Downlink peak spectral efficiency | Throughput / (12 · RB · SCS) | 20 b/s/Hz | 30 b/s/Hz |
| Uplink peak spectral efficiency | Throughput / (12 · RB · SCS) | 20 b/s/Hz | 30 b/s/Hz |
| Network energy efficiency | Throughput / Energy, relative to baseline | 1× | 30× |
| Peak user data rate | SE × bandwidth / concurrent users | 100 Mb/s | 1 Gb/s |
| Minimum user latency | Payload / Throughput (= TTI) | 1 ms | 0.1 ms |

Throughput = Payload / Timeslot.

## Getting started

```bash
python run.py --serve    # web UI at http://127.0.0.1:8810
python run.py            # console report using the assumptions in config/
python run.py --all      # also writes HTML, Markdown and JSON reports to out/
```

In the web UI, `예시 불러오기` loads a sample input; editing a cell recalculates immediately. The assumptions tab recalculates from adjustable assumptions (sliders).

## Input format

A single long-form CSV with columns `item,case,param,value`. `case` is `baseline` (conventional 5G setup) or `proposed`.

```
item,case,param,value
se_dl,proposed,payload_bits,1474593
se_dl,proposed,slot_ms,0.5
se_dl,proposed,n_rb,273
se_dl,proposed,scs_khz,30
```

Each value can be supplied in several ways; a directly supplied value takes precedence.

| item | Accepted parameters |
|---|---|
| `se_dl`, `se_ul` | `se` · `throughput_mbps` + `n_rb` + `scs_khz` · `payload_bits` + `slot_ms` + `n_rb` + `scs_khz` |
| `lat` | `latency_ms` · `payload_bits` + `throughput_mbps` |
| `rate` | `rate_mbps` · `throughput_mbps` · `se` + `bw_mhz` + `users` |
| `ee` | `throughput_mbps` + `power_w` (baseline and proposed) · `ee_ratio` (proposed) |

Items with missing inputs are not calculated; the report lists what is needed. Assumptions live in `config/assumptions.json` and external inputs in `config/inputs.json`.

## Project layout

```
run.py               entry point (CLI and web server)
wireless/            formulas, input parsing, reports, web UI
config/              assumptions and inputs
tests/               unittest suite
```

## Tests

```bash
python -m unittest discover -s tests
```

## Acknowledgement

This work was supported by Institute of Information & communications Technology Planning & Evaluation (IITP) grant funded by the Korea government(MSIT) (No.RS-2022-00155911, Artificial Intelligence Convergence Innovation Human Resources Development (Kyung Hee University)),(No.2019-0-01287, Evolvable Deep Learning Model Generation Platform for Edge Computing)

## License

Apache-2.0
