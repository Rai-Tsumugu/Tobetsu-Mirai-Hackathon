import unittest

from auto_repair_items.core import DEMO_DATE, Store, ValidationError, demo_item, seed_demo
from auto_repair_items.m06 import SPEC, run


class M06Tests(unittest.TestCase):
    def setUp(self):
        self.store = Store()
        seed_demo(self.store)

    def tearDown(self):
        self.store.close()

    def record(self, *, item=None, **changes):
        payload = {
            'action': 'record_event',
            'item': item or demo_item(unit_price='125'),
            'event_type': 'increase',
            'reason': '仕入価格の確認に基づく改定',
            'source': 'simulator:架空価格表',
            'confirmed_by': '架空確認者',
            'occurred_at': DEMO_DATE,
        }
        payload.update(changes)
        return run(payload, self.store)

    def test_defaults_append_event_and_return_only_approved_latest_price(self):
        result = run(SPEC['defaults'], self.store)

        self.assertEqual(result['event']['event_type'], 'increase')
        self.assertEqual(result['event']['old_version'], self.store.price_versions(
            'demo-paint', '販売')[0]['price_version_id'])
        self.assertEqual(result['event']['new_version'], result['price_version']['price_version_id'])
        self.assertEqual(result['event']['actor'], '架空デモ担当')
        self.assertEqual(result['event']['source'], 'simulator:架空値')
        self.assertEqual(result['items'][0]['unit_price'], '125')
        self.assertEqual(result['items'][0]['source'], 'simulator:架空値')
        self.assertTrue(result['simulator'])

    def test_each_change_and_its_price_version_are_append_only(self):
        first = self.record()
        second = self.record(item=demo_item(unit_price='130'), event_type='correction',
                             reason='入力額を伝票で訂正', occurred_at='2026-10-12T09:30:00+09:00')

        events = self.store.records('price_event', 'demo-paint')
        versions = self.store.price_versions('demo-paint', '販売')
        self.assertEqual(len(events), 2)
        self.assertEqual(len(versions), 3)  # one seeded sale version plus two changes
        self.assertEqual(events[0]['new_version'], first['price_version']['price_version_id'])
        self.assertEqual(events[1]['old_version'], first['price_version']['price_version_id'])
        self.assertEqual(events[1]['new_version'], second['price_version']['price_version_id'])
        self.assertEqual(events[1]['occurred_at'], '2026-10-12T09:30:00+09:00')
        self.assertEqual(second['items'][0]['unit_price'], '130')

    def test_pending_event_is_recorded_but_does_not_replace_approved_item(self):
        result = self.record(status='pending', item=demo_item(unit_price='150'))

        self.assertEqual(result['event']['status'], 'pending')
        self.assertEqual(result['items'][0]['unit_price'], '120')
        current = self.store.get_price('demo-paint', '販売', as_of=DEMO_DATE)
        self.assertEqual(current['item']['unit_price'], '120')
        self.assertNotEqual(current['price_version_id'], result['price_version']['price_version_id'])

    def test_first_price_requires_initial_event_type(self):
        item = demo_item(item_id='new-item', unit_price='25')
        with self.assertRaisesRegex(ValidationError, 'initial'):
            self.record(item=item)
        result = self.record(item=item, event_type='initial')

        self.assertIsNone(result['event']['old_version'])
        self.assertEqual(result['items'], [item | {'source': 'simulator:架空価格表'}])

    def test_invalid_input_does_not_write_price_or_event(self):
        for changes in (
            {'event_type': 'unknown'},
            {'reason': ' '},
            {'source': ''},
            {'confirmed_by': ''},
            {'occurred_at': 'tomorrow'},
        ):
            with self.subTest(changes=changes), self.assertRaises(ValidationError):
                self.record(**changes)
        with self.assertRaisesRegex(ValidationError, '既存価格の変更'):
            self.record(event_type='initial')
        self.assertEqual(len(self.store.price_versions('demo-paint', '販売')), 1)
        self.assertEqual(self.store.records('price_event'), [])

    def test_history_lookup_is_scoped_to_item(self):
        self.record()
        result = run({'action': 'list_events', 'item_id': 'demo-paint'}, self.store)

        self.assertEqual(len(result['events']), 1)
        self.assertNotIn('record_id', result['events'][0])
        self.assertEqual(run({'action': 'list_events', 'item_id': 'missing'}, self.store)['events'], [])

    def test_rejects_non_dict_payload_and_unknown_action(self):
        for payload in (None, [], {'action': 'delete_event'}):
            with self.subTest(payload=payload), self.assertRaises(ValidationError):
                run(payload, self.store)


if __name__ == '__main__':
    unittest.main()
