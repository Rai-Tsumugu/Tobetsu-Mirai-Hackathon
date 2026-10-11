import copy, unittest
from .contract import common_scenario_fixture
from .e29 import queue_snapshot, sync_snapshot

class E29Tests(unittest.TestCase):
    def test_queue_is_immutable_idempotent_and_version_pinned(self):
        source=common_scenario_fixture(); original=[]
        q=queue_snapshot(original,'snap-1',source,'v1'); q2=queue_snapshot(q,'snap-1',source,'v1')
        self.assertEqual(original,[]); self.assertEqual(q2,q); self.assertEqual(q[0]['status'],'pending')
        self.assertEqual(q[0]['rule_version'],'v1')
        with self.assertRaisesRegex(ValueError,'idempotency_conflict'):
            queue_snapshot(q,'snap-1',source,'v2')
    def test_modified_snapshot_body_is_rejected_before_sync_or_rebase(self):
        snapshot=queue_snapshot([],'snap-integrity',common_scenario_fixture(),'v1')[0]
        snapshot['scenario_input']['person_count']=99
        result=sync_snapshot(snapshot,'v2',resolution='rebase_to_server',actor='owner',reason='try altered data')
        self.assertEqual(result['status'],'snapshot_integrity_error')
        self.assertEqual(result['rule_version'],'v1')
    def test_version_conflict_waits_for_audited_human_choice(self):
        snapshot=queue_snapshot([],'snap-1',common_scenario_fixture(),'v1')[0]
        conflict=sync_snapshot(snapshot,'v2'); self.assertEqual(conflict['status'],'version_conflict')
        kept=sync_snapshot(snapshot,'v2',resolution='keep_snapshot',actor='owner',reason='keep original rules')
        self.assertEqual(kept['rule_version'],'v1'); self.assertEqual(kept['status'],'ready_with_pinned_version')
        rebased=sync_snapshot(snapshot,'v2',resolution='rebase_to_server',actor='owner',reason='recalculate with approved rules')
        self.assertEqual(rebased['rule_version'],'v2')
        self.assertEqual(rebased['scenario_input']['rule_version'],'v2')
        self.assertEqual(sync_snapshot(rebased,'v2')['status'],'ready_to_recompute')
        with self.assertRaisesRegex(ValueError,'actor_and_reason'):
            sync_snapshot(snapshot,'v2',resolution='rebase_to_server')
