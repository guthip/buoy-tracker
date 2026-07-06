# Replay fixtures

JSONL files for `POST /api/debug/replay` (simulation mode only — see
`[debug]` in `config/environment.config`, `enable_simulation = true`).

One packet per line:

```json
{"type": "position", "delay_s": 2.0, "packet": { ...json_packet dict... }}
```

- `type`: `position` | `telemetry` | `nodeinfo`
- `delay_s`: real-time gap to the previous packet; divided by the replay
  `speed` factor (e.g. `delay_s: 120` at `speed: 60` sleeps 2 s)
- `packet`: the decoded json_packet exactly as the handlers consume it —
  the same shape `src/simulation.py` builders produce

Only files inside this directory can be replayed (no path traversal).
See `example_drift.jsonl` for a 3-gateway drift burst; replace the node id
and coordinates with your own.
