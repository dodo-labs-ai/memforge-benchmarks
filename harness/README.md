# Stale document pilot

When a stale document and the current one both exist, how often does a coding agent follow the stale one, and what changes that?

This repository is the harness for a capped feasibility pilot of that question. Its numbers test the harness and are not findings. The documents are synthetic.

## Design

Three small code tasks. Each is a tiny repository, a prompt that does not reveal the answer, and an executable assertion that classifies the finished workspace as `old`, `new` or `neither`. No model judges anything.

| Group | What the agent has |
|---|---|
| A | No documents. A pass here is leakage. |
| B | The documents in the repository, with shell and file tools. |
| C | B plus a short `AGENTS.md` index naming which document is current. |
| D | No documents in the repository. The real MemForge plugin, connected to a sandbox MemForge that synced the same documents. |

Three runs per group per task, 36 at most. The agent is Codex CLI 0.166.0 with `gpt-6-luna` through an OpenAI-compatible endpoint.

The six documents are separate live files with neutral names and no banner saying which replaced which. File times are invented and set on each copy, so B, C and D see the same times. D's memories carry them as document times.

## Isolation

Every run gets its own home, Codex home and repository under `WORK_ROOT/<opaque id>`, with one commit and no parent repository. Those directories are deleted once the run's records are copied out.

Commands run under a permission profile that is an allowlist: the system, Homebrew's tools and the run's own home to read, the repository and a private temporary directory to write, no network. Codex's stock workspace-write profile reads the whole disk, including the developer's own Codex configuration, so this project does not use it.

Group D's home starts from a template installed through the public marketplace with `codex plugin marketplace add` and `codex plugin add`. Each run copies only the installed plugin. The marketplace checkout stays behind because its tree holds these same documents, and leaving its configuration out stops Codex cloning it again at every start.

`python3 -m harness.pilot preflight` proves this with no model call and writes `results/isolation/preflight.json`. Each run then checks its own session records, and the sandbox's access log has to account for every memory tool call.

## Running it

You need Docker, Codex CLI and an env file naming `MEMFORGE_RELAY_BASE_URL`, `MEMFORGE_RELAY_API_KEY`, `MEMFORGE_RELAY_MODEL` and `OPENROUTER_API_KEY`. Only those four names are read from the file.

```bash
export EXPERIMENT_ENV_FILE=/path/to/env
python3 -m harness.sandbox up        # clone the pinned MemForge, build, start on loopback
python3 -m harness.sandbox prepare   # set models, sync the documents, wait for relation discovery
python3 -m harness.home template     # install the plugin through the marketplace
python3 -m harness.pilot selftest    # each assertion against known solutions
python3 -m harness.pilot preflight
nohup python3 -m harness.pilot run > pilot.log 2>&1 &
python3 -m harness.report
python3 -m harness.sandbox down
```

`run` is resumable. A run with a line in `results/runs.jsonl` is skipped, and a recorded `results/STOP.json` blocks further runs until you pass `--clear-stop`. It commits to this repository after each batch, after `harness.scan` finds no key, endpoint or developer path.

The limits are 10 minutes per run, 6 retries across the pilot and only for transport failures, a total of 60 million tokens, and a stop on any rate limit.

## Auditing a run

`results/runs.jsonl` has one line per run with its outcome, what it read, memory tools, relation notices, tokens, duration and isolation checks. `results/attempts.jsonl` adds attempts that were retried.

`results/transcripts/<task>__<group>__<rep>` holds the raw `codex exec --json` events, the session rollout with everything the model was shown, stderr, and the diff of the workspace. Each line's `rerun_command` repeats that run into another results directory.

`python3 -m harness.pilot audit` replays every recorded diff on a fresh task repository and classifies it again. `python3 -m harness.pilot reparse` recomputes what the records derive from their transcripts. `results/isolation/` holds the preflight, each batch's window on the sandbox's access log, the whole access log, and the developer project's state before and after.

Judge a run on its rollout, not only its events: the event stream leaves out commands the sandbox refuses at once.

`results/REPORT.md` is built from these files by `python3 -m harness.report`.

## Using your own cases

Add a directory under `tasks/` with `task.json`, `repo/`, `assert_outcome.py` and `fixtures/{old,new,neither}.py`, and add its documents to `corpus/`. `python3 -m harness.pilot selftest` checks the assertion.
