# Prefill and total decode speed

Total decode is the sum of actual token deliveries across all requests over the same shared wall-clock interval. Per-request decode is the median over that identical interval. Prefill is effective burst prefill including queueing and mixed decode. A dash means the wave never had all requested streams decoding simultaneously; it is not zero throughput.

| Input tokens/request | Requested C | Prefill tok/s | Total decode tok/s | Decode tok/s/request | Shared seconds | Peak overlap |
|---:|---:|---:|---:|---:|---:|---:|
| 512 | 1 | 1324.60 | 70.69 | 70.69 | 14.47 | 1 |
| 512 | 4 | 2525.14 | 156.03 | 39.70 | 25.20 | 4 |
| 512 | 16 | 2357.95 | 341.73 | 21.46 | 44.89 | 16 |
| 2048 | 1 | 2554.66 | 72.96 | 72.96 | 14.02 | 1 |
| 2048 | 4 | 3112.65 | 164.90 | 41.09 | 24.32 | 4 |
| 2048 | 16 | 3154.90 | 345.69 | 21.20 | 44.57 | 16 |
| 8192 | 1 | 3238.14 | 71.60 | 71.60 | 14.29 | 1 |
| 8192 | 4 | 3356.75 | 159.92 | 39.77 | 24.73 | 4 |
| 8192 | 16 | 3388.08 | 353.03 | 22.56 | 43.74 | 16 |
| 32768 | 1 | 3351.81 | 69.17 | 69.17 | 14.79 | 1 |
| 32768 | 4 | 3403.66 | 168.87 | 42.21 | 23.85 | 4 |
| 32768 | 16 | 3391.31 | 355.40 | 22.30 | 42.89 | 16 |
| 131072 | 1 | 3113.18 | 70.88 | 70.88 | 14.43 | 1 |
| 131072 | 4 | 3109.48 | 151.10 | 38.08 | 25.28 | 4 |
| 131072 | 16 | 2959.88 | 324.97 | 20.37 | 48.39 | 16 |
| 524288 | 1 | 2283.67 | 62.02 | 62.02 | 16.50 | 1 |
| 524288 | 4 | 2265.39 | 144.18 | 35.96 | 27.28 | 4 |
| 524288 | 16 | 2280.40 | — | — | 0.00 | 10 |
