# Stage 1 pilot report

**The pilot exercises the harness. Its outcomes are not findings: each cell ran once, and none counts toward the formal result.**

Run on 2026-11-09 with Codex CLI 0.167.0, `gpt-6-luna`, and MemForge at `33a69927`.

## What ran

| Step | Result | Tokens |
|---|---|---|
| Sync GOV.UK small: 30 documents, real edit times, project `mfd` | success, 297 memories, 297 of 297 relation slices complete, 45 minutes | 1,346,251 generation |
| t01 and t06 in B, C1, C2, D, small | 8 of 8 completed, no retry | 1,149,959 |
| t01 and t06 in D, large, project `mfrel` | 2 of 2 completed, no retry | 349,722 |

All 10 runs finished on the first attempt with no isolation violation. A run took 34 to 60 seconds and 88,000 to 215,000 tokens.

## Outcomes

| Task | A (stage 0, 3 runs) | B | C1 | C2 | D small | D large |
|---|---|---|---|---|---|---|
| t01 | neither 3 | old | old | old | new | new |
| t06 | old 3 | old | old | old | old | old |

## What the runs showed

- **t01 C1:** the run read the indexed new document, then found the old one by listing the folder, called it "the newer bootstrap section" without any evidence, and followed it. The index names only one revision and does not call it current.
- **t01 D small:** the relation was stored and the older memory carried its notice; the run followed the newer memory.
- **t01 D large:** this corpus stores no relation for the pair. Both memories were returned, and the run took the higher-ranked one, which was the new one. That is not evidence for the relation.
- **t06:** the old command is also what the model writes with no documents (A: old 3 of 3). The new revision warns against shell access but prescribes no alternative. C1 read the new document in full and still wrote `kubectl exec ... printenv`, reasoning that printing one variable answers the warning. D small and D large stored no relation for the pair.

## Harness items

- **Token guard.** `Ledger.tokens_used` counts cached input twice and reserves 1,000,000 for the next run, so the 2,500,000 default stopped the run at 887,262 tokens as reported. The rest ran with `--token-cap 4500000`; the real total stayed under 2,500,000. A formal cap has to be set on that measure.
- **Codex pin.** Homebrew moved Codex to 0.167.0 on 2026-11-09 and removed 0.166.0. The pin is now 0.167.0 and the loopback checks pass on it. Group A's screen ran on 0.166.0.
- **Exposure field.** `revision_text_seen` matches document phrases, so it reads false when a D run sees only a memory's paraphrase. It does not measure D's exposure.
- **D network.** Each D run opens `github.com:443` from Codex's background plugin sync, which the other groups have turned off.

## Not exercised

B-t, real edit times for sets other than GOV.UK, and the group-D sync at large scale with real edit times.

## Version pin for the formal runs

On 2026-11-10 the pin moved to the public release: memforge-ai 0.2.0b4 at `7f0aa5e4`, and plugin 0.2.0-beta.4 installed from its release tag at the same commit. Between `33a69927`, where the pilot and pre-check ran, and `7f0aa5e4`, the only changes under `src/` are the two plugin version strings.

Checked with no generation call: the task checks, `harness_check` and `trials_check` pass; a fresh Compose project at the pin builds, reports 0.2.0b4 and accepts both models. Group D's path with the new plugin passed against the existing GOV.UK small sync, which runs at `33a69927`.

# Pre-check

Run on 2026-11-09 with Codex CLI 0.167.0 and `gpt-6-luna`, after t10's shared corner probe was removed. Each of the 8 scored tasks ran three times with no documents (A) and three times with the small folder minus the task's own old revision (N). The N rule was written down before the runs: a task with fewer than two `new` in N cannot measure version choice. The closed-book rule is stage 0's: a task with two or more `new` in A is excluded.

48 runs completed, with 10 transport failures retried, no isolation violation, and 5,359,994 tokens.

| Task | A | N | Result |
|---|---|---|---|
| t01 GOV.UK database role | neither 3 | new 3 | kept |
| t09 Django browser tests | old 3 | new 3 | kept |
| t16 Rust Forge rollup approval | neither 3 | new 3 | kept |
| t18 OpenTelemetry attribute | neither 3 | new 3 | kept |
| t10 gRPC `principal_name` | new 3 | new 3 | excluded: closed-book rule |
| t02 GitLab API field | neither 3 | old 3 | excluded: N rule |
| t06 GOV.UK environment variable | old 3 | old 3 | excluded: N rule |
| t08 Django warning names | old 3 | old 3 | excluded: N rule |

- **t02:** the new revision keeps the old answer as its third choice, so the runs that read it were still following it.
- **t06:** the new revision warns against a shell and names no alternative.
- **t08:** the new revision gives only the pattern `RemovedInDjangoXXXXWarning`, and the run filled it from the repository's version, a two-digit name.
- **t10:** on Codex 0.166.0 all three closed-book runs answered with the old fallback rule; on 0.167.0 all three answered with the new one. Only the Codex version and the removed shared probe differ on the harness side, and the probe cannot change the answers on the probes where the revisions disagree.

Four tasks remain, under the design's floor of six.

# Candidate tasks

Five new tasks, chosen because the new revision prescribes something a program can check, went through the same two checks with the same rules, written down before the runs. 30 runs completed with no retry and no isolation violation, using 2,719,456 tokens.

| Task | A | N | Result |
|---|---|---|---|
| t20 Rust Forge dev desktop access | neither 3 | new 3 | passed |
| t21 Rust Forge stable priority command | neither 3 | new 3 | passed |
| t22 OpenTelemetry `rpc.status_code` | old 3 | new 3 | passed |
| t24 Django release key import | old 2, neither 1 | new 3 | passed |
| t23 OpenTelemetry exception recording | neither 3 | neither 3 | excluded: N rule |

- **t23:** all six runs imported `opentelemetry`, which the check's environment lacks, so the check could not score them. This is a defect of the check, not evidence about the task. It is excluded as the rule says and not repaired, because eight tasks pass without it.
- **t22** is a weak test of staleness in the same way as t18: the new revision lists the old key as Deprecated.

Eight tasks pass both checks: t01, t09, t16, t18, t20, t21, t22 and t24, from four document sets (GOV.UK, Django, OpenTelemetry, Rust Forge). No passing task uses the GitLab or gRPC sets.
