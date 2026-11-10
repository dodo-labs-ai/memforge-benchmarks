# Kestrel

A small job queue. `kestrel/worker.py` decides what happens to a job that raised
an error; `kestrel/retry.py` holds the retry schedule.
