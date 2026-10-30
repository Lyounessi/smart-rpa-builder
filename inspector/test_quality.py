from django.test import SimpleTestCase

from .quality import assess_id, initial_quality, record_observation


class SelectorQualityTests(SimpleTestCase):
    def setUp(self):
        self.metadata = {'tag':'input', 'role':'textbox', 'name':'Supplier name', 'label':'Supplier name', 'attributes':{'id':'supplier-name'}}
        self.locator = {'strategy':'label', 'value':'Supplier name'}

    def test_id_patterns_are_clues_not_proof(self):
        self.assertEqual(assess_id('supplier-name')['assessment'], 'unverified')
        for value in [':r4:', 'input-4829', 'customer-12345-name', 'radix-12', 'field-a83f6b12', 'Ab3xY']:
            self.assertEqual(assess_id(value)['assessment'], 'suspected_generated')
        self.assertEqual(assess_id('')['assessment'], 'absent')

    def test_repeat_tests_same_document_do_not_increase_evidence(self):
        quality = initial_quality(self.metadata, self.locator, 'document-1', 'session-1')
        result = {'status':'unique', 'identity_matches':True, 'observed_id':'supplier-name', 'document_id':'document-1'}
        for _ in range(5):
            quality = record_observation(quality, result, 'session-1')
        self.assertEqual(quality['assessment'], 'unverified')
        self.assertEqual(len(quality['observations']), 1)

    def test_new_document_builds_evidence_and_changed_id_is_recorded(self):
        quality = initial_quality(self.metadata, self.locator, 'document-1', 'session-1')
        updated = record_observation(quality, {'status':'unique', 'identity_matches':True, 'observed_id':'supplier-new', 'document_id':'document-2'}, 'session-2')
        self.assertEqual(updated['assessment'], 'observed_across_documents')
        self.assertEqual(updated['id']['assessment'], 'observed_changing')
        self.assertEqual(len(updated['observations']), 2)

    def test_failed_and_unverified_matches_cannot_be_called_stable(self):
        quality = initial_quality(self.metadata, self.locator, 'document-1', 'session-1')
        for status in ['missing', 'ambiguous', 'hidden', 'identity_mismatch', 'error']:
            self.assertEqual(record_observation(quality, {'status':status}, 'session-2')['assessment'], 'needs_review')
        self.assertEqual(record_observation({}, {'status':'unique'}, 'session-2')['assessment'], 'unverified')
