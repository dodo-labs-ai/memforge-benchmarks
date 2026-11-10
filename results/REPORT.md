# Stale document pilot

**Pilot. These numbers test the harness; they are not findings.** Three synthetic tasks, three runs per group per task, one model, one coding agent. Nothing here supports a claim about agents or tools in general.

Runs with a result: 36 of 36. Attempts: 36, by status {'completed': 36}. Retries used: 0.

## Group by outcome

| Group | old | new | neither | runs |
|---|---|---|---|---|
| A | 2 | 0 | 7 | 9 |
| B | 6 | 3 | 0 | 9 |
| C | 1 | 8 | 0 | 9 |
| D | 3 | 6 | 0 | 9 |

## By task

| Task (old/new/neither) | A | B | C | D |
|---|---|---|---|---|
| failure-alerts | 0/0/3 | 2/1/0 | 0/3/0 | 0/3/0 |
| job-retries | 0/0/3 | 1/2/0 | 0/3/0 | 0/3/0 |
| queue-stall | 2/0/1 | 3/0/0 | 1/2/0 | 3/0/0 |

## Leakage: group A, no documents

A pass here means the right answer did not need the documents.

| Task | A passes (new) | A old | A neither | What the assertion saw |
|---|---|---|---|---|
| failure-alerts | 0 | 0 | 3 | ack_deadline_seconds() == 300; alert_channel() == '#on-call'; ack_deadline_seconds() raised NotImplementedError:  |
| job-retries | 0 | 0 | 3 | retry_delays() == [1, 2, 4, 8, 16]; retry_delays() == [1, 5, 30, 300, 1800]; retry_delays() == [1, 5, 30, 60] |
| queue-stall | 0 | 2 | 1 | fsync_guard=True; watchdogs=[('seconds_since_last_job_started', 300, 'page_oncall'), ('oldest_pending_job_age'; fsync_guard=True; watchdogs=[('seconds_since_last_job_started', 60, 'page_oncall'), ('oldest_pending_job_age', |

## What the agent looked at

| Group | runs | read current doc | read stale doc | looked at file times | called memory tool | saw current memory | saw stale memory | saw any relation notice | saw this task's notice |
|---|---|---|---|---|---|---|---|---|---|
| A | 9 | 0 | 0 | 1 | 0 | 0 | 0 | 0 | 0 |
| B | 9 | 8 | 9 | 2 | 0 | 0 | 0 | 0 | 0 |
| C | 9 | 9 | 3 | 0 | 0 | 0 | 0 | 0 | 0 |
| D | 9 | 0 | 0 | 0 | 9 | 9 | 9 | 9 | 6 |

## What MemForge made of the documents

| Task | memories (stale / current) | linked | label | document times (stale / current) |
|---|---|---|---|---|
| job-retries | 3 / 1 | yes | updates | 2026-07-08T09:30:00+00:00 / 2026-10-02T14:10:00+00:00 |
| failure-alerts | 1 / 1 | yes | updates | 2026-08-11T08:05:00+00:00 / 2026-10-09T11:45:00+00:00 |
| queue-stall | 2 / 2 | yes | equivalent | 2026-09-20T16:20:00+00:00 / 2026-10-14T10:00:00+00:00 |

Sandbox commit `ab35f5066a752893ea0b2f66fc5e69d1ba09a9a9`. Generation gpt-6-luna through an OpenAI-compatible endpoint; embedding openai/text-embedding-3-small through openrouter. Relation work: {'completed': 10}. Model usage logged by MemForge: gpt-6-luna: 27 calls, 49754 prompt and 3928 completion tokens.

## Isolation

Runs with an isolation violation: 0.

Commands or outputs naming a path outside the run's own directory: 0.

Commands issued, from the session records: 252. Absent from the JSON event stream: 7. Refused by the sandbox: 7.

- 5 x `find: ..: Operation not permitted`

- 2 x `zsh:1: operation not permitted: python`

Group A, 2 batch(es): 0 requests reached the sandbox through its port during them; memories and links unchanged in every batch: True.

Group B, 2 batch(es): 0 requests reached the sandbox through its port during them; memories and links unchanged in every batch: True.

Group C, 2 batch(es): 0 requests reached the sandbox through its port during them; memories and links unchanged in every batch: True.

Group D, 2 batch(es): 26 requests reached the sandbox through its port during them; memories and links unchanged in every batch: True.

Group D: 9 of 9 runs have sandbox requests covering every memory tool call that succeeded.

## Tokens and time

Agent across all attempts, as measured: 3870847 input (of which 3340160 cached) and 37851 output. Harness probes: 249560. MemForge's own model calls: 53682. Counter against the 60000000 cap, which adds input, cached input and output as reported: 7745892.

| Group | runs | mean input | mean cached input | mean output | mean total | min total | max total | mean s | median s | max s |
|---|---|---|---|---|---|---|---|---|---|---|
| A | 9 | 116422 | 103538 | 1315 | 117737 | 97456 | 164374 | 87.3 | 81.0 | 162.1 |
| B | 9 | 99164 | 85660 | 1103 | 100267 | 61710 | 136989 | 63.5 | 66.6 | 80.2 |
| C | 9 | 69084 | 58951 | 776 | 69860 | 46456 | 100369 | 41.8 | 44.7 | 64.1 |
| D | 9 | 145425 | 122980 | 1011 | 146436 | 108742 | 194716 | 57.1 | 52.7 | 80.8 |

## Projection for 240 runs

240 runs at the pilot's per-group means: 26.1 million tokens (25.8 million input, of which 22.3 million cached, and 0.25 million output). With every run at its group's largest pilot value: 35.8 million.

Agent time: 4.2 hours one at a time, 1.4 hours if every group ran at concurrency 3, 2.0 hours as this harness runs them, with group D one at a time.

This scales the pilot and is not a forecast. Group D's searches returned the whole ten-memory corpus; twenty tasks will change the size of what a search returns. Sync and relation discovery for 40 documents are not included.

## Every run

| Run | status | outcome | input | cached input | output | seconds | turns | read current | read stale | memory tools | notice |
|---|---|---|---|---|---|---|---|---|---|---|---|
| failure-alerts/A/1 | completed | neither | 163060 | 143488 | 1314 | 162.1 | 1 | no | no | - | no |
| failure-alerts/A/2 | completed | neither | 114171 | 108416 | 963 | 58.1 | 1 | no | no | - | no |
| failure-alerts/A/3 | completed | neither | 112748 | 103552 | 1073 | 87.7 | 1 | no | no | - | no |
| failure-alerts/B/1 | completed | old | 135707 | 124288 | 1282 | 80.2 | 1 | yes | yes | - | no |
| failure-alerts/B/2 | completed | old | 98369 | 68480 | 1354 | 63.1 | 1 | yes | yes | - | no |
| failure-alerts/B/3 | completed | new | 117243 | 111104 | 1066 | 65.8 | 1 | yes | yes | - | no |
| failure-alerts/C/1 | completed | new | 45977 | 40832 | 479 | 21.7 | 1 | yes | no | - | no |
| failure-alerts/C/2 | completed | new | 62705 | 41600 | 656 | 44.7 | 1 | yes | no | - | no |
| failure-alerts/C/3 | completed | new | 61772 | 58112 | 566 | 25.7 | 1 | yes | no | - | no |
| failure-alerts/D/1 | completed | new | 134081 | 109824 | 681 | 46.2 | 1 | no | no | searchx1,get_memoryx1 | yes |
| failure-alerts/D/2 | completed | new | 107958 | 79872 | 784 | 51.2 | 1 | no | no | searchx1 | yes |
| failure-alerts/D/3 | completed | new | 161676 | 140416 | 989 | 52.7 | 1 | no | no | searchx1,get_memoryx1 | yes |
| job-retries/A/1 | completed | neither | 96981 | 91648 | 1095 | 72.5 | 1 | no | no | - | no |
| job-retries/A/2 | completed | neither | 116667 | 110208 | 1432 | 81.0 | 1 | no | no | - | no |
| job-retries/A/3 | completed | neither | 96370 | 87040 | 1086 | 62.6 | 1 | no | no | - | no |
| job-retries/B/1 | completed | new | 100792 | 74368 | 956 | 68.3 | 1 | yes | yes | - | no |
| job-retries/B/2 | completed | old | 61329 | 49536 | 381 | 23.7 | 1 | no | yes | - | no |
| job-retries/B/3 | completed | new | 79826 | 75008 | 948 | 57.3 | 1 | yes | yes | - | no |
| job-retries/C/1 | completed | new | 62789 | 58752 | 501 | 45.0 | 1 | yes | no | - | no |
| job-retries/C/2 | completed | new | 46171 | 40192 | 484 | 35.1 | 1 | yes | no | - | no |
| job-retries/C/3 | completed | new | 61857 | 58240 | 480 | 24.1 | 1 | yes | no | - | no |
| job-retries/D/1 | completed | new | 137596 | 122752 | 964 | 58.5 | 1 | no | no | searchx1,get_memoryx1 | yes |
| job-retries/D/2 | completed | new | 118659 | 100480 | 765 | 43.9 | 1 | no | no | searchx1,get_memoryx1 | yes |
| job-retries/D/3 | completed | new | 131455 | 96512 | 840 | 50.1 | 1 | no | no | searchx1,get_memoryx1 | yes |
| queue-stall/A/1 | completed | old | 128919 | 92928 | 1490 | 81.9 | 1 | no | no | - | no |
| queue-stall/A/2 | completed | neither | 101285 | 84096 | 1697 | 79.9 | 1 | no | no | - | no |
| queue-stall/A/3 | completed | old | 117595 | 110464 | 1686 | 100.0 | 1 | no | no | - | no |
| queue-stall/B/1 | completed | old | 100004 | 93440 | 1507 | 69.5 | 1 | yes | yes | - | no |
| queue-stall/B/2 | completed | old | 98476 | 83328 | 1131 | 66.6 | 1 | yes | yes | - | no |
| queue-stall/B/3 | completed | old | 100727 | 91392 | 1306 | 77.0 | 1 | yes | yes | - | no |
| queue-stall/C/1 | completed | new | 98979 | 83584 | 1390 | 62.7 | 1 | yes | yes | - | no |
| queue-stall/C/2 | completed | old | 83002 | 70016 | 1123 | 53.5 | 1 | yes | yes | - | no |
| queue-stall/C/3 | completed | new | 98501 | 79232 | 1304 | 64.1 | 1 | yes | yes | - | no |
| queue-stall/D/1 | completed | old | 193025 | 176640 | 1691 | 80.8 | 1 | no | no | searchx1,get_memoryx1 | other |
| queue-stall/D/2 | completed | old | 163299 | 133888 | 1313 | 73.8 | 1 | no | no | searchx1,get_memoryx1 | other |
| queue-stall/D/3 | completed | old | 161076 | 146432 | 1074 | 57.0 | 1 | no | no | searchx1,get_memoryx1 | other |
