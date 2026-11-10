# Pre-registered plan: does a coding agent use the current revision of a document?

Published on 2026-11-10. The tag `preregistration-v1` marks this version. No formal run has started.

**Who runs this.** The MemForge maintainers designed this experiment and will run it, and MemForge is one of the things it tests. We have an interest in the outcome. So the tasks, the conditions, the scoring and the analysis are fixed here before the formal runs, and we will publish the results whatever they show.

## Questions

When an old and a new revision of a document sit side by side:

1. How often does a coding agent use the new revision?
2. Does that change when the documents grow from 30 to several hundred?
3. How much do a hand-written docs index and MemForge each change the result, and what does each cost in tokens?

## What is tested

| Item | Fixed value |
|---|---|
| Agent | Codex CLI 0.167.0 |
| Model under test | `gpt-6-luna`, reasoning effort medium |
| MemForge server | `memforge-ai` 0.2.0b4, commit `7f0aa5e4`, self-hosted through Docker Compose |
| MemForge plugin | `0.2.0-beta.4`, installed through the public marketplace from its release tag |
| MemForge generation model | `gpt-6-luna` |
| MemForge embedding model | `text-embedding-3-small` |

These results describe this combination only.

## Documents

All text is public and unmodified. The repository stores links, commits and hashes, and a script fetches the text.

| Set | Repository | Commit | Licence | Small | Large |
|---|---|---|---|---|---|
| GOV.UK developer docs | `alphagov/govuk-developer-docs` | `c3b7a0cf` | MIT | 30 | 246 |
| Django docs | `django/django` | `1860f0a3` | BSD-3-Clause | 30 | 682 |
| OpenTelemetry semantic conventions | `open-telemetry/semantic-conventions` | `35ee31c3` | Apache-2.0 | 30 | 307 |
| Rust Forge | `rust-lang/rust-forge` | `4486d498` | Apache-2.0 OR MIT | 30 | 153 |

**Staging.** Each task's old and new revisions are placed in the folder together, as two files with neutral names of the same style. The names do not say which revision is which. Four tasks give the old revision the first name and four give it the second. Each task keeps its arrangement in every condition.

**Small set.** 30 documents: every staged pair from that set, and other documents chosen by a fixed hash ranking. Documents that state a task's old or new rule are left out of that draw, so the small set tests the pair alone.

**Large set.** Every document in the set plus every staged pair. It contains the small set under the same paths. Other documents at this size can still state a task's old or new rule. Each task's record counts them.

**File times.** Every document and code file has one fixed time, except in B-t and in the folder group D syncs, which carry each document's real last-edit time.

## Tasks

A task is a real, public change of a documented decision, a small coding request that depends on it, and a program that scores the result. No model judges any outcome.

| Task | Set | Decision that changed | How far the outcome can be trusted |
|---|---|---|---|
| t01 | GOV.UK | The database admin secret is read acting as `tempadmin`, no longer `fulladmin` | `new` is clean. Other live pages still name `fulladmin`, so `old` does not prove the old revision misled the run |
| t09 | Django | Browser integration tests moved from Selenium to Playwright | Clean. A user-facing guide outside the pair still teaches Selenium |
| t16 | Rust Forge | The rollup approval command gained a required `force` | Clean, but a one-token difference |
| t18 | OpenTelemetry | `service.peer.*` was deprecated in favour of `server.service.*` on the client side | **Weak test of staleness.** The new revision marks the old key Deprecated, so a run that opens both can tell which is newer |
| t20 | Rust Forge | A contributor gets a dev desktop through a pull request, no longer by email | Clean |
| t21 | Rust Forge | The command that gives way to a stable release is `@bors yield`, no longer `@bors retry` | Clean |
| t22 | OpenTelemetry | `rpc.response.status_code` was renamed `rpc.status_code` | **Weak test of staleness**, for the same reason as t18 |
| t24 | Django | A release manager's key is imported from GitHub, and the keyserver route is gone | `old` is clean. GitHub appears in both revisions, so `new` means no keyserver at all |

### How the tasks were chosen

Tasks were chosen because the answer depends on a settled decision, which favours a memory tool. Conclusions apply to this kind of task only.

Each candidate went through two checks, with the rules written down before the runs and no MemForge result involved:

- **Closed book (group A, 3 runs, no documents).** Two or more `new` means the model already knows the answer, and the task is dropped.
- **New revision only (group N, 3 runs, the small folder without the task's old revision).** Fewer than two `new` means the task cannot measure which revision a run chose, and it is dropped.

Three runs is a weak filter. A task the model answers correctly 30% of the time still passes the closed-book check about 78% of the time.

| Dropped task | Reason |
|---|---|
| t02 GitLab API field | N: the new revision keeps the old answer as a third choice |
| t05 GitLab Vue translation | Dropped on review: a change of emphasis, not a reversal |
| t06 GOV.UK environment variable | N: the new revision warns against a command and names no alternative |
| t08 Django warning names | N: the new revision gives only a placeholder |
| t10 gRPC `principal_name` | Closed book: 3 of 3 `new` on Codex 0.167.0 |
| t12 gRPC ejection limit | Closed book: 2 of 3 `new` on Codex 0.166.0, not rerun |
| t23 OpenTelemetry exception recording | N: a defect in our scoring program. Excluded as the rule says, and not repaired |

## Conditions

| Group | What the agent has | Sizes |
|---|---|---|
| A | No documents | One size-independent baseline |
| B | Documents in the repository, no index | Small, large |
| B-t | As B, with real file times | Large |
| C1 | As B, plus an `AGENTS.md` index of at most 50 lines whose line for this task names the new revision | Small, large |
| C2 | The same index, whose line for this task names the old revision | Small, large |
| D | No documents in the repository. The agent reads them through the MemForge plugin, from a server that has synced the same folder | Small, large |

Each cell runs 3 times. That is 216 runs for the 9 document cells of the 8 tasks, plus group A's 24 runs, which were completed during the task checks on the same Codex version. The total is 240.

C1 and C2 stand for the two states one index line can be in for a task: updated or not. An index with no line for the task is close to B. We do not assume how often a real index goes stale.

## Procedure

- For each document set, the small-size runs come first. MemForge then continues syncing the same workspace up to the large set, and the large-size runs follow.
- Within one set and size, all groups are interleaved in an order fixed by a seed, and one run happens at a time.
- Group D runs only if the server holds the full document count for that set and size.
- Every run has a new home directory, a file-access allowlist and no network for commands. The prompt is fixed and does not mention the experiment. Group D has the plugin's read tools approved, and every tool that writes memory stays refused.
- A run has 600 seconds. A timeout or an error is rerun once, and a transport failure is retried after a pause. Every attempt is logged, and the latest attempt of a run stands.
- A rate limit, an isolation violation or the token cap stops the series until the cause is understood.

## Outcomes and measures

The scoring program reads only the code a run changed, and reports one outcome:

| Outcome | Meaning |
|---|---|
| `new` | The deliverable follows the new revision |
| `old` | The deliverable follows the old revision |
| `neither` | There is a deliverable, and it follows neither |
| `declined` | No deliverable |
| `failed` | Codex did not finish the run. It is outside every rate |

**Primary measure: the `new` rate**, which is `new` divided by all finished runs. `declined` counts as a finished run. We do not use the `old` rate as the primary measure, because `old` can come from the model's habit or from other live documents, while `new` shows the new information arrived.

**Secondary measures:**

- `old`, `neither` and `declined` rates.
- Total input, uncached input and output tokens, and time per run.
- Whether a run opened each revision. For group D this comes from its memory calls, because the document-phrase check cannot see a memory's paraphrase.
- For group D: whether the tools were called, where the new and old memories ranked, and whether a relation notice reached the agent.
- For MemForge: whether the relevant memories were extracted, whether a relation was stored and what its label was.
- Sync tokens and time per set, and how many runs it takes to recover the sync cost.

## Comparisons fixed in advance

1. `new` rate at large size: D against B.
2. `new` rate at large size: D against C1, and D against C2.
3. Effect of size: the gain of D over B at large size minus the same gain at small size.
4. Tokens per run at each size: D against B.
5. `new` rate at large size: B-t against B, which shows how much real file times matter. Group D can see real times, so this sizes that difference.

**Method.** For each task, compute the difference between the two conditions, using its finished runs. Resample the 8 tasks with replacement 10,000 times, with a fixed seed, and report the mean difference with the percentile 95% interval. Comparison 3 uses the same method on the per-task difference of differences. A task with no finished run in a compared cell is left out of that comparison and named in the report.

Eight tasks give wide intervals. When an interval includes 0 we will write only that no difference was seen. We make no correction for testing five comparisons, so a single interval that barely excludes 0 is weak evidence. Per-task results are published in full, and we will also report comparisons 1 to 3 without t18 and t22.

`formal/harness/analysis.py` computes the `new` rate and these comparisons, with seed 20261110, and is part of this commit. Comparison 4 is reported for total, uncached input and output tokens. Memory ranks, stored relations and sync costs are descriptive, and are read from the run transcripts and the server after the runs.

## How the results will be reported

| Result | What we will say |
|---|---|
| At large size D is clearly better than B and C2, and close to C1 | A maintained index is still enough. An index that is not updated stops working, and MemForge does not depend on someone updating one. This holds for this set of tasks |
| D is about the same as C2 | We report it, and we do not claim MemForge stops stale documents from misleading an agent |
| D is no better than B | We report it, and we narrow what we claim |
| D still costs more tokens than B at large size | We report it, and we do not claim token savings |
| D rarely calls the tools, or does not find the right memory | This becomes the main finding |

If cost or an outage stops the series before every cell is finished, we publish the finished cells and say what did not run.

## What has already been seen

- **First harness pilot.** Three synthetic tasks on synthetic documents, 36 runs, recorded in `results/REPORT.md`. It tests the harness, and none of its tasks or documents is used here.
- **Second pilot.** t01 and the now-dropped t06 ran once per cell in B, C1, C2 and D at small size, and once in D at large size. These 10 runs test the harness and do not count, and `formal/stage1/REPORT.md` records them. For t01, B, C1 and C2 scored `old`, and D scored `new` at both sizes. At large size no relation was stored for that pair, so the run took the higher-ranked memory.
- **MemForge before the freeze.** MemForge was changed during normal development before the version above was frozen, and t01's pair was inspected while checking one of those changes.
- **Group A** ran during the task checks and is reused here. The checks are recorded in `formal/stage0/REPORT.md` and `formal/stage1/REPORT.md`.
- **Records.** Each of these runs has a structured record in this repository. Raw transcripts quote the documents, so they are held back until each set's licence terms have been checked. `formal/transcripts.sha256` lists their hashes, so the later publication can be checked against this commit.
- **Screening.** Codex moved from 0.166.0 to 0.167.0 during screening, so every task still in contention was checked again on 0.167.0. Part-way through screening, gateway errors were reclassified as transport failures and retried. That did not change any task's result.

## Known limits

- **Staged coexistence.** Most of these changes were made in place upstream. We put the old revision back beside the new one. The text is unchanged, but the situation is partly built by us.
- **Conditions differ.** Group D trusts the plugin's hooks and has read tools approved. Each group D run also opens `github.com:443` from Codex's background plugin sync, which other groups have turned off. Groups B and C have the documents in the repository, while many teams keep theirs in a wiki, and that favours B and C.
- **Scale.** The largest set is 682 documents, far smaller than a big company's knowledge base.
- **Single combination.** One agent and one model. A later model that has learned these changes needs the tasks screened again.
- **Network logging** covers Codex only, not the MemForge container.
- **Silent deletion is not scored.** A document that was removed with no replacement is outside this experiment.

## Changes after publication

Any change to this plan after the date above is added here with its date and reason. Tasks will not be replaced after publication.

| Date | Change | Reason |
|---|---|---|
| | None yet | |
