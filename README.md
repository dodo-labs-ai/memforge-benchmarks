# MemForge benchmarks

Public evaluations of [MemForge](https://github.com/dodo-labs-ai/mem-forge), run by its maintainers and fixed in advance.

## Does a coding agent use the current revision of a document?

The first evaluation. When an old and a new revision of a real document sit side by side, how often does a coding agent follow the new one, does that change as the documents grow from 30 to several hundred, and what do a hand-written docs index and MemForge each change and cost?

**Status: no formal run has started.** The tasks, conditions, scoring and analysis are fixed in [PREREGISTRATION.md](PREREGISTRATION.md). The tag `preregistration-v1` marks the registered version, and any later change is listed in that file with its date and reason.

**Who runs this.** The MemForge maintainers designed this experiment and will run it, and MemForge is one of the things it tests. The results will be published whatever they show.

| Path | What it holds |
|---|---|
| [PREREGISTRATION.md](PREREGISTRATION.md) | The plan |
| `formal/corpus/` | Pinned repositories, commits and hashes, and the script that fetches the documents |
| `formal/tasks/` | Each task's prompt, code, scoring program and fixtures |
| `formal/harness/` | The runner, the checks and the analysis |
| `formal/stage0/`, `formal/stage1/` | Records of the task checks and the pilot |
| `harness/`, `tasks/`, `corpus/`, `results/` | The first harness pilot on synthetic documents, whose isolation, parser and ledger the formal runs reuse |

To rebuild and check the tasks, see [formal/README.md](formal/README.md). A check of the analysis needs no model and no key:

```bash
python3 -m formal.harness.analysis selftest
```

## Licence

The code and records here are under the Apache License 2.0. The documents the experiment reads belong to their projects, under the licences listed in the plan, and are not stored in this repository.
