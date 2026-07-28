# Formal Dataset Audit

Generated at: `2026-07-28T21:51:19.616590+00:00`

- Raw final runs: 60
- Included valid runs: 60
- Excluded invalid runs: 0
- Runs by arm: `{"B": 20, "C": 20, "D": 20}`
- Global errors log empty: `true`
- Recovered intermediate parse warnings: 1

Invalid final runs are excluded from valid-case aggregation. Recovered
intermediate attempts remain part of a successful end-to-end run. Valid
negative security findings remain included rather than being relabeled as
infrastructure errors.

See `data-audit-manifest.json` for every run SHA-256 and decision.
