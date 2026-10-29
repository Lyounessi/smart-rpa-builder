from decimal import Decimal
from io import BytesIO, StringIO
from pathlib import Path
from types import SimpleNamespace
import tempfile
from unittest.mock import Mock

from django.core.exceptions import ValidationError
from django.core.management import call_command
from django.test import TestCase, TransactionTestCase, override_settings
from django.urls import reverse
from PIL import Image

from inspector.models import ApplicationWindow, CapturedElement
from projects.models import Dataset, DatasetRow, Project, ProjectInput, StepElementReference, WorkflowStep
from .budget import SpendingPolicy, close_abandoned, reserve, settle
from .client import MuseError
from .context import create_snapshot, prepare_context, request_context, require_current
from .models import ContextSnapshot, MuseBudget, MuseRequest
from .service import MuseService


@override_settings(MUSE_APIKEY='fictional-api-key', META_MODEL='muse-spark-1.3', MUSE_BUDGET_USD='140',
    MUSE_MAX_OUTPUT_TOKENS='4096', META_PRICE_MODEL='muse-spark-1.3', META_INPUT_USD_PER_MILLION='1.25',
    META_CACHED_USD_PER_MILLION='0.15', META_OUTPUT_USD_PER_MILLION='4.25')
class Phase2Tests(TestCase):
    def setUp(self):
        self.folder = tempfile.TemporaryDirectory()
        self.addCleanup(self.folder.cleanup)
        override = override_settings(MEDIA_ROOT=self.folder.name)
        override.enable()
        self.addCleanup(override.disable)
        self.project = Project.objects.create(name='Context fixture', automation_goal='Register fictional suppliers')
        self.window = ApplicationWindow.objects.create(project=self.project, name='Portal', target_url='https://example.invalid/')
        self.column = ProjectInput.objects.create(project=self.project, key='name')
        self.element = CapturedElement.objects.create(window=self.window, name='Name', locator={'strategy':'label','value':'Name'})
        self.step = WorkflowStep.objects.create(project=self.project, window=self.window, position=1, name='Fill',
            instruction='Fill the mapped field', action='fill', input_column=self.column)
        StepElementReference.objects.create(step=self.step, element=self.element)

    def attach(self, element=None, name='capture.png', color='white'):
        path = Path(self.folder.name) / name
        Image.new('RGB', (80, 60), color).save(path, format='PNG')
        element = element or self.element
        element.highlighted_screenshot.name = name
        element.save()
        return path

    def response(self, text='OK', usage=True, status='completed'):
        return SimpleNamespace(status=status, output_text=text, usage=SimpleNamespace(input_tokens=100,
            output_tokens=20, input_tokens_details=SimpleNamespace(cached_tokens=40)) if usage else None)

    def test_context_is_filtered_stable_and_hybrid(self):
        self.attach()
        unused = CapturedElement.objects.create(window=self.window, name='UNRELATED_ELEMENT', locator={})
        dataset = Dataset.objects.create(project=self.project, name='Private', source_name='fixture', headers=['name'], schema_snapshot=[])
        DatasetRow.objects.create(dataset=dataset, row_number=2, values={'name':'PRIVATE_DATASET_VALUE'})
        first, second = create_snapshot(self.project), create_snapshot(self.project)
        self.assertEqual(first.specification_hash, second.specification_hash)
        self.assertEqual(first.contract_version, '1.0')
        instructions, input = request_context(first)
        self.assertIn('BaseRobot', instructions)
        self.assertIn('ExampleRobot', instructions)
        self.assertNotIn(self.project.automation_goal, instructions)
        self.assertNotIn('PRIVATE_DATASET_VALUE', str(input))
        self.assertNotIn(str(unused.pk), str(input))
        self.assertNotIn('fictional-api-key', str(input))
        blocks = input[0]['content']
        self.assertEqual(blocks[0]['type'], 'input_text')
        self.assertTrue(next(block['image_url'] for block in blocks if block['type'] == 'input_image').startswith('data:image/png;base64,'))
        self.assertNotIn(str(self.folder.name), str(input))
        with self.assertRaises(ValidationError):
            first.save()

    def test_duplicate_screenshots_sent_once_and_labels_preserved(self):
        self.attach()
        element = CapturedElement.objects.create(window=self.window, name='Submit', locator={'strategy':'text','value':'Submit'}, highlighted_screenshot='capture.png')
        step = WorkflowStep.objects.create(project=self.project, window=self.window, position=2, name='Submit', instruction='Click', action='click')
        StepElementReference.objects.create(step=step, element=element)
        snapshot = create_snapshot(self.project)
        self.assertEqual(len(snapshot.images), 1)
        self.assertEqual(set(snapshot.images[0]['element_ids']), {str(self.element.pk), str(element.pk)})

    def test_changes_to_brief_mappings_and_image_content_detect_stale(self):
        path = self.attach()
        snapshot = create_snapshot(self.project)
        require_current(snapshot)
        self.project.global_rules = 'Do not duplicate'
        self.project.save()
        with self.assertRaises(MuseError) as caught:
            require_current(snapshot)
        self.assertEqual(caught.exception.code, 'stale_specification')
        snapshot = create_snapshot(self.project)
        self.step.instruction = 'Different instruction'
        self.step.save()
        with self.assertRaises(MuseError):
            require_current(snapshot)
        snapshot = create_snapshot(self.project)
        Image.new('RGB', (80,60), 'blue').save(path)
        with self.assertRaises(MuseError):
            require_current(snapshot)

    def test_known_secret_and_unsafe_or_missing_images_fail_closed(self):
        self.project.global_rules = 'fictional-api-key'
        self.project.save()
        with self.assertRaises(MuseError) as caught:
            prepare_context(self.project)
        self.assertEqual(caught.exception.code, 'sensitive_context')
        self.project.global_rules = ''
        self.project.save()
        for name in ['missing.png', '../outside.png']:
            self.element.highlighted_screenshot.name = name
            self.element.save()
            with self.assertRaises(MuseError):
                create_snapshot(self.project)

    def test_image_and_text_limits_and_saved_image_integrity(self):
        from unittest.mock import patch
        self.attach()
        with patch('muse_builder.context.MAX_IMAGES', 0), self.assertRaises(MuseError):
            prepare_context(self.project)
        with patch('muse_builder.context.MAX_TEXT_BYTES', 5), self.assertRaises(MuseError):
            prepare_context(self.project)
        snapshot = create_snapshot(self.project)
        saved = Path(self.folder.name) / snapshot.images[0]['path']
        saved.write_bytes(b'changed')
        with self.assertRaises(MuseError):
            request_context(snapshot)

    def test_connection_is_budgeted_and_usage_cost_is_persisted(self):
        client = Mock()
        client.request.return_value = self.response()
        result = MuseService(client=client).check_connection()
        request = MuseRequest.objects.get(pk=result.request_id)
        self.assertEqual(request.outcome, 'success')
        self.assertEqual((request.input_tokens, request.output_tokens, request.cached_tokens), (100,20,40))
        self.assertEqual(request.estimated_cost_usd, Decimal('0.00016600'))
        self.assertEqual(MuseBudget.objects.get().committed_usd, request.estimated_cost_usd)
        self.assertIsNone(request.active_slot)
        self.assertEqual(client.request.call_count, 1)

    def test_budget_and_one_active_operation_block_without_provider_call(self):
        client = Mock()
        active = reserve('context_review', 'muse-spark-1.3', 1024)
        with self.assertRaises(MuseError) as caught:
            MuseService(client=client).check_connection()
        self.assertEqual(caught.exception.code, 'operation_active')
        client.request.assert_not_called()
        close_abandoned(active.pk)
        with override_settings(MUSE_BUDGET_USD='0.01'), self.assertRaises(MuseError) as caught:
            MuseService(client=client).check_connection()
        self.assertEqual(caught.exception.code, 'budget_exhausted')
        client.request.assert_not_called()

    def test_unknown_usage_and_timeout_keep_full_reservations(self):
        client = Mock()
        client.request.return_value = self.response(usage=False)
        MuseService(client=client).check_connection()
        first = MuseRequest.objects.get()
        self.assertEqual(first.accounted_usd, first.reserved_usd)
        self.assertFalse(first.usage_known)
        client.request.side_effect = MuseError('timeout', 'Safe timeout')
        with self.assertRaises(MuseError):
            MuseService(client=client).check_connection()
        second = MuseRequest.objects.first()
        self.assertEqual(second.outcome, 'uncertain')
        self.assertEqual(second.accounted_usd, second.reserved_usd)
        self.assertEqual(MuseBudget.objects.get().committed_usd, first.reserved_usd + second.reserved_usd)

    def test_rejected_request_releases_and_double_settlement_is_blocked(self):
        client = Mock()
        client.request.side_effect = MuseError('authentication', 'Safe auth error')
        with self.assertRaises(MuseError):
            MuseService(client=client).check_connection()
        request = MuseRequest.objects.get()
        self.assertEqual(request.accounted_usd, 0)
        self.assertEqual(MuseBudget.objects.get().committed_usd, 0)
        with self.assertRaises(MuseError):
            close_abandoned(request.pk)

    def test_stale_before_request_blocks_and_change_during_request_discards_response(self):
        snapshot = create_snapshot(self.project)
        self.project.success_criteria = 'New success test'
        self.project.save()
        client = Mock()
        with self.assertRaises(MuseError):
            MuseService(client=client).review_context(snapshot)
        client.request.assert_not_called()
        self.assertEqual(MuseRequest.objects.count(), 0)
        snapshot = create_snapshot(self.project)
        def response(**kwargs):
            Project.objects.filter(pk=self.project.pk).update(global_rules='Changed during operation')
            return self.response(text='Review response')
        client.request.side_effect = response
        with self.assertRaises(MuseError) as caught:
            MuseService(client=client).review_context(snapshot)
        self.assertEqual(caught.exception.code, 'stale_specification')
        request = MuseRequest.objects.get()
        self.assertEqual(request.outcome, 'stale')
        self.assertTrue(request.usage_known)
        self.assertGreater(request.accounted_usd, 0)

    def test_output_caps_unpriced_model_and_bad_prices_block_before_api(self):
        snapshot = create_snapshot(self.project)
        client = Mock()
        for kwargs in [{'MUSE_MAX_OUTPUT_TOKENS':'10'}, {'META_PRICE_MODEL':'other'}, {'META_INPUT_USD_PER_MILLION':'nan'}]:
            with override_settings(**kwargs), self.assertRaises(MuseError):
                MuseService(client=client).check_connection()
        for cap in [0, 4097]:
            with self.assertRaises(MuseError):
                MuseService(client=client).review_context(snapshot, max_output_tokens=cap)
        client.request.assert_not_called()

    def test_incomplete_response_still_accounts_usage_without_retry(self):
        client = Mock()
        client.request.return_value = self.response(status='incomplete', text='')
        with self.assertRaises(MuseError):
            MuseService(client=client).check_connection()
        self.assertEqual(MuseRequest.objects.get().outcome, 'failed')
        self.assertGreater(MuseBudget.objects.get().committed_usd, 0)
        self.assertEqual(client.request.call_count, 1)

    def test_safe_usage_page_and_local_snapshot_command(self):
        output = StringIO()
        call_command('prepare_muse_context', self.project.pk, stdout=output)
        self.assertIn('No API request made', output.getvalue())
        self.assertEqual(MuseRequest.objects.count(), 0)
        response = self.client.get(reverse('muse-usage'))
        self.assertContains(response, 'not a provider billing guarantee')
        self.assertNotContains(response, 'fictional-api-key')
        self.assertNotContains(response, self.project.automation_goal)


@override_settings(MUSE_BUDGET_USD='140', META_PRICE_MODEL='muse-spark-1.3', MUSE_MAX_OUTPUT_TOKENS='4096')
class ConcurrentReservationTests(TransactionTestCase):
    def test_racing_workers_get_at_most_one_active_reservation(self):
        from concurrent.futures import ThreadPoolExecutor
        from threading import Barrier
        from django.db import close_old_connections
        MuseBudget.objects.create(pk=1)
        barrier = Barrier(2)
        def worker():
            close_old_connections()
            try:
                barrier.wait(timeout=5)
                try:
                    return str(reserve('context_review', 'muse-spark-1.3', 1024).pk)
                except MuseError:
                    return None
            finally:
                close_old_connections()
        with ThreadPoolExecutor(max_workers=2) as executor:
            results = list(executor.map(lambda _:worker(), range(2)))
        self.assertLessEqual(sum(result is not None for result in results), 1)
        self.assertEqual(MuseRequest.objects.filter(active_slot='local').count(), sum(result is not None for result in results))
        self.assertEqual(MuseBudget.objects.get().committed_usd, sum(request.accounted_usd for request in MuseRequest.objects.all()))
