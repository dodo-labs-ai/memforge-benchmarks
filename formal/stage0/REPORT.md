# Stage 0 report

**Stage 0 prepares the experiment. Nothing here is a finding about agents or tools.**

Setup: Codex CLI 0.166.0 and `gpt-6-luna` at medium effort through an OpenAI-compatible endpoint. The closed-book screen uses no documents and no MemForge.

Eight tasks survived the closed-book screen. The pre-check in `../stage1/REPORT.md` then changed that list.

## Document sets

| Set | Commit | Files | Bytes |
|---|---|---|---|
| GOV.UK | c3b7a0cfbe83 | 245 | 1,281,079 |
| GitLab | d03b20d5a631 | 668 | 8,368,421 |
| Django | 1860f0a3f41e | 680 | 6,541,190 |
| OpenTelemetry | 35ee31c3a16a | 305 | 4,066,026 |
| gRPC | 4125fbd15535 | 200 | 2,056,198 |
| Rust Forge | 4486d498cc6b | 150 | 729,960 |

The largest set is 680 files. Manifests are in `formal/corpus/manifests/`.

## Closed-book screen

Three runs per task with no documents. A task is excluded when two or more runs reach `new`.

| Task | old | new | neither | declined | Result |
|---|---|---|---|---|---|
| t01 GOV.UK database role | 0 | 0 | 3 | 0 | kept |
| t02 GitLab API field | 0 | 0 | 3 | 0 | kept |
| t06 GOV.UK environment variable | 3 | 0 | 0 | 0 | kept |
| t08 Django warning names | 2 | 0 | 1 | 0 | kept |
| t09 Django browser tests | 3 | 0 | 0 | 0 | kept |
| t10 gRPC `principal_name` | 0 | 0 | 3 | 0 | kept, marked |
| t12 gRPC ejection limit (reserve) | 1 | 2 | 0 | 0 | excluded |
| t16 Rust Forge rollup approval | 0 | 0 | 3 | 0 | kept, promoted |
| t18 OpenTelemetry attribute | 0 | 0 | 3 | 0 | kept |

- **t05 was dropped on review before the screen.** It is a change of emphasis, not a reversal.
- **t10 is marked.** All three runs wrote the old fallback rule but scored `neither`, because they fail a corner probe shared by both revisions, so its old baseline is understated.
- **The attempt rule changed during the screen.** The endpoint returned gateway errors on 7 of 34 attempts. Gateway pages then became transport failures with more retries, and two runs were rerun. No task's result changed, and all attempts stay in `screen/attempts.jsonl`.
- **Three runs are a weak screen.** A task the model answers `new` 30% of the time still passes about 78% of the time.

Egress: all 34 attempts reached only the endpoint, through a logging proxy. A direct connection opened and closed between two half-second polls would be missed.

## Index size

Codex 0.166.0 cuts `AGENTS.md` at exactly 32,768 bytes by default, and nothing tells the model or the user. A bare list of paths fits for every set; GitLab's takes 26,285 bytes, which leaves about 9.7 bytes per line for any description.
