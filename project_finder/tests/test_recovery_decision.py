import unittest

from project_finder.recovery_decision import build_recovery_plan


class RecoveryDecisionTests(unittest.TestCase):
    def test_states_map_to_safe_actions(self):
        report = {
            'items': [
                {'path': 'a.py', 'state': 'IDENTICAL'},
                {'path': 'b.py', 'state': 'LOCAL_ONLY', 'repo': 'Sire65/Dienstplan'},
                {'path': 'c.py', 'state': 'DIVERGENT', 'repo': 'Sire65/Dienstplan'},
                {'path': 'd.py', 'state': 'POSSIBLE_MATCH'},
                {'path': 'e.py', 'state': 'REPO_UNAVAILABLE'},
                {'path': 'f.py', 'state': 'UNASSIGNED'},
            ]
        }
        plan = build_recovery_plan(report)
        decisions = {row['path']: row['decision'] for row in plan['items']}
        self.assertEqual(decisions['a.py'], 'NO_ACTION')
        self.assertEqual(decisions['b.py'], 'RECOVERY_BRANCH_CANDIDATE')
        self.assertEqual(decisions['c.py'], 'MANUAL_REVIEW')
        self.assertEqual(decisions['d.py'], 'VERIFY_CONTENT')
        self.assertEqual(decisions['e.py'], 'DEFER')
        self.assertEqual(decisions['f.py'], 'ASSIGN_REPOSITORY')

    def test_plan_never_claims_a_github_write(self):
        plan = build_recovery_plan({'items': [{'path': 'x.py', 'state': 'LOCAL_ONLY'}]})
        self.assertTrue(plan['read_only'])
        self.assertFalse(plan['github_write_performed'])
        self.assertFalse(plan['main_modified'])
        self.assertFalse(plan['items'][0]['github_write_performed'])
        self.assertFalse(plan['items'][0]['main_modified'])


if __name__ == '__main__':
    unittest.main()
