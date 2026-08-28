import unittest

from project_finder.cloud_contract import CloudJob, compact_result


class CloudContractTests(unittest.TestCase):
    def test_cloud_job_rejects_cleanup(self):
        job = CloudJob(
            job_id='job-1', device_id='pc-1', profile_name='overnight',
            roots=['E:\\KC'], requested_at='2026-08-28T20:00:00+0200', allow_cleanup=True,
        )
        with self.assertRaises(ValueError):
            job.to_payload()

    def test_compact_result_omits_full_local_paths_and_hashes(self):
        summary = {
            'status': 'SUCCESS', 'profile': 'overnight', 'files': 9123,
            'bytes': 123456789, 'duplicates': 421, 'run_dir': 'E:\\private\\run',
        }
        findings = [{
            'name': 'KC_DP2_v1.zip', 'path': 'E:\\secret\\KC_DP2_v1.zip',
            'sha256': 'abc', 'size': 42, 'status': 'BLUE',
            'proposed_action': 'QUARANTINE', 'confidence': 95,
        }]
        payload = compact_result(summary, findings=findings)
        self.assertNotIn('run_dir', payload)
        self.assertNotIn('path', payload['findings'][0])
        self.assertNotIn('sha256', payload['findings'][0])
        self.assertEqual(payload['files'], 9123)


if __name__ == '__main__':
    unittest.main()
