# Simultaneous delivered decode throughput

Counts actual emitted token IDs in one shared wall-clock interval: after the last stream starts emitting and before the first stream stops emitting. This includes scheduling stalls and speculative bursts. Windows under two seconds are flagged. No overlap means this burst cannot establish throughput at the requested simultaneous concurrency.

| Input tokens | C | Shared seconds | Aggregate tok/s | Median tok/s/request | Status |
|---:|---:|---:|---:|---:|---|
| 512 | 1 | 14.47 | 70.69 | 70.69 | measured |
| 512 | 4 | 25.20 | 156.03 | 39.70 | measured |
| 512 | 16 | 44.89 | 341.73 | 21.46 | measured |
| 2048 | 1 | 14.02 | 72.96 | 72.96 | measured |
| 2048 | 4 | 24.32 | 164.90 | 41.09 | measured |
| 2048 | 16 | 44.57 | 345.69 | 21.20 | measured |
| 8192 | 1 | 14.29 | 71.60 | 71.60 | measured |
| 8192 | 4 | 24.73 | 159.92 | 39.77 | measured |
| 8192 | 16 | 43.74 | 353.03 | 22.56 | measured |
| 32768 | 1 | 14.79 | 69.17 | 69.17 | measured |
| 32768 | 4 | 23.85 | 168.87 | 42.21 | measured |
| 32768 | 16 | 42.89 | 355.40 | 22.30 | measured |
| 131072 | 1 | 14.43 | 70.88 | 70.88 | measured |
| 131072 | 4 | 25.28 | 151.10 | 38.08 | measured |
| 131072 | 16 | 48.39 | 324.97 | 20.37 | measured |
| 524288 | 1 | 16.50 | 62.02 | 62.02 | measured |
| 524288 | 4 | 27.28 | 144.18 | 35.96 | measured |
| 524288 | 16 | — | — | — | request_failure |
