import unittest

from project_finder.cloud_job_state import JobLease, claim_job, finish_job, heartbeat


class CloudJobStateTests(unittest.TestCase):
    def test_wrong_device_cannot_claim(self):
        row = JobLease(job_id="j1", device_id="pc-a")
        with self.assertRaises(PermissionError):
            claim_job(row, device_id="pc-b", worker_id="w1", now=100)

    def test_live_lease_blocks_second_worker(self):
        row = claim_job(JobLease(job_id="j1", device_id="pc-a"), device_id="pc-a", worker_id="w1", now=100)
        with self.assertRaises(RuntimeError):
            claim_job(row, device_id="pc-a", worker_id="w2", now=120)

    def test_expired_lease_can_be_reclaimed(self):
        row = claim_job(JobLease(job_id="j1", device_id="pc-a"), device_id="pc-a", worker_id="w1", now=100, lease_seconds=30)
        row = claim_job(row, device_id="pc-a", worker_id="w2", now=131, lease_seconds=30)
        self.assertEqual(row.claimed_by, "w2")
        self.assertEqual(row.attempt, 2)

    def test_terminal_job_cannot_run_twice(self):
        row = claim_job(JobLease(job_id="j1", device_id="pc-a"), device_id="pc-a", worker_id="w1", now=100)
        row = heartbeat(row, worker_id="w1", now=110)
        row = finish_job(row, worker_id="w1", status="SUCCESS", result_digest="abc")
        with self.assertRaises(RuntimeError):
            claim_job(row, device_id="pc-a", worker_id="w1", now=200)


if __name__ == "__main__":
    unittest.main()
