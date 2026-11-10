import unittest

from kestrel.job import Job
from kestrel.retry import retry_delays
from kestrel.worker import next_step


class WorkerTest(unittest.TestCase):
    def test_every_delay_is_a_positive_number_of_seconds(self):
        delays = retry_delays()
        self.assertTrue(delays)
        self.assertTrue(all(isinstance(delay, int) and delay > 0 for delay in delays))

    def test_a_job_out_of_retries_is_dead_lettered(self):
        job = Job(id="j1", attempts=len(retry_delays()))
        self.assertEqual(next_step(job), ("dead-letter", None))


if __name__ == "__main__":
    unittest.main()
