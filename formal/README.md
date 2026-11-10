# Formal experiment

Work for the formal experiment. The pilot's harness and results stay where they are, one level up, and this reuses its isolation, parser, scrubber and ledger.

`stage0/` holds the task screen. `stage1/` holds the second pilot and the pre-checks. The plan the formal runs follow is `PREREGISTRATION.md`, one level up.

Each run keeps one structured record in its `runs.jsonl`, which is what the analysis reads. Raw transcripts quote the documents and stay out of git until each set's licence terms have been checked, so a re-derivation of old records needs a local copy of them. `transcripts.sha256` lists their hashes.

| Path | What it holds |
|---|---|
| `corpus/sets.json`, `corpus/manifests/`, `corpus/revisions.json` | Pinned repositories, commits and globs, with each file's size and sha256 |
| `corpus/fetch_corpus.py` | Fetches the text into `corpus/fetched/`, which git ignores, and checks it against the manifests |
| `corpus/ingest_check.py` | Runs MemForge's own file selection, lifted from a clone, on every set |
| `corpus/coexist.py` | The rule that stages old and new side by side: neutral names, rotation, small and large sets |
| `corpus/contamination.py` | Counts other documents that state a task's old or new rule |
| `tasks/<id>/` | `task.json`, `repo/`, `assert_outcome.py` and `fixtures/` |
| `tasks/assertlib.py` | What the assertions share. Standard library only |
| `harness/check_tasks.py` | Reversals, leaks, imports and every fixture |
| `harness/harness_check.py` | The run settings, proved through Codex with a loopback stand-in for the model |
| `harness/screen.py` | The closed-book screen, resumable, at most three runs at a time |
| `harness/egress.py` | What each run's Codex process connects to, through a logging proxy and a poll from outside it |
| `harness/budget.py` | The stage's running token total against its cap |
| `harness/index_probe.py` | One real run: how much of a long AGENTS.md reaches the model |
| `harness/trials.py` | The runs of every group, one at a time in a seeded order |
| `harness/analysis.py` | The `new` rate and the five comparisons of the published plan. Pass it the formal results and the two pre-check directories that hold group A, never the pilot |
| `stage0/` | The recorded output of each of these, and `progress.log` |

## Rebuilding it

```bash
export EXPERIMENT_ENV_FILE=/path/to/env               # only four allowlisted names are read
export EXPERIMENT_SCAN_PATTERNS=/path/to/patterns     # local patterns for the scan and the scrubber
python3 -m formal.corpus.fetch_corpus                 # fails if any text differs from the manifests
python3 -m formal.corpus.ingest_check --memforge /path/to/a/clone
python3 -m formal.corpus.coexist plan --memforge /path/to/a/clone
python3 -m formal.corpus.contamination
python3 -m formal.harness.check_tasks
python3 -m formal.harness.harness_check               # no model call
python3 -m harness.scan                               # before each commit
```

The screen is the first step that calls a model:

```bash
nohup python3 -m formal.harness.screen run --tasks all > /dev/null 2>&1 &
python3 -m formal.harness.screen report
python3 -m formal.harness.screen audit
```

## Outcomes

An assertion reads only the code a run changed and reports one of four outcomes:

| Outcome | Meaning |
|---|---|
| `new` | The deliverable follows the new revision |
| `old` | The deliverable follows the old revision |
| `neither` | There is a deliverable, and it follows neither |
| `declined` | No deliverable: the workspace is untouched, only notes were written, or the stub still raises `NotImplementedError` |

The screen adds `failed` for a run Codex did not finish, whatever its workspace shows. Such a run stays out of every rate.

Each task's `separation` and `weak_points` say how far its outcomes can be trusted.
