from datetime import timedelta
from io import StringIO
import importlib

from django.apps import apps
from django.core.management import call_command
from django.test import TestCase
from django.urls import reverse
from django.utils import timezone

from projects.models import Dataset, DatasetRow, Project
from .adapters import DjangoQueue, create_run
from .catalog import register_manual_build
from .models import ActionRecord, ProgressEvent, Robot, RobotBuild, RobotRun, RowAttempt
from .robot_views import run_metrics


class CatalogTests(TestCase):
    def setUp(self):
        self.project = Project.objects.create(name='Catalog project')
        self.robot = Robot.objects.create(project=self.project, name='ROBOT_CATALOG_PROJECT')
        self.build = RobotBuild.objects.create(robot=self.robot, version=1, origin='manual', status='registered',
            source_files={'example.py':'<script>do_not_execute()</script>'},
            configuration={'robot_name':self.robot.name}, validation_report=['Manual registration only.'])
        self.dataset = Dataset.objects.create(project=self.project, name='Records', source_name='fixture', headers=['name'],
            schema_snapshot=[], status='ready', row_count=4)
        self.rows = [DatasetRow.objects.create(dataset=self.dataset, row_number=n + 2, values={'name':f'Fictional {n}'}) for n in range(4)]
        self.start = timezone.now() - timedelta(minutes=1)
        self.run = RobotRun.objects.create(dataset=self.dataset, robot_name=self.robot.name, build=self.build,
            state='completed', active_slot=None, heartbeat=timezone.now(), started_at=self.start,
            finished_at=self.start + timedelta(seconds=10), counts={'OK':999})

    def attempt(self, index, outcome='', business=False, elapsed=None):
        return RowAttempt.objects.create(run=self.run, row=self.rows[index], outcome=outcome,
            business_completed_at=self.start if business else None,
            started_at=self.start if elapsed is not None else None,
            finished_at=self.start + timedelta(seconds=elapsed) if elapsed is not None else None)

    def test_kpis_preserve_business_success_despite_notification_error(self):
        self.attempt(0, 'OK', True, 2)
        attempt = self.attempt(1, 'ERROR', True, 4)
        ActionRecord.objects.create(attempt=attempt, step_id='notify', status='failed', message='Email was not accepted.')
        self.attempt(2, 'NOK')
        self.attempt(3)
        metrics = run_metrics(self.run)
        self.assertEqual(metrics['business_completed'], 2)
        self.assertEqual(metrics['ok'], 1)
        self.assertEqual(metrics['errors'], 1)
        self.assertEqual(metrics['nok'], 1)
        self.assertEqual(metrics['unconfirmed'], 1)
        self.assertEqual(metrics['completion_rate'], '50.0%')
        self.assertEqual(metrics['elapsed'], '10.0s')
        self.assertEqual(metrics['average'], '3.0s')
        response = self.client.get(reverse('robot-detail', args=[self.robot.pk]))
        self.assertContains(response, 'Email was not accepted.')
        self.assertContains(response, 'Fictional 0')
        self.assertContains(response, '50.0%')
        self.assertContains(response, '10.0s')

    def test_run_selection_is_scoped_to_robot_and_legacy_timing_is_not_invented(self):
        self.run.started_at = self.run.finished_at = None
        self.run.build = None
        self.run.save()
        response = self.client.get(reverse('robot-detail', args=[self.robot.pk]))
        self.assertContains(response, 'Not recorded')
        self.assertContains(response, 'Legacy / unknown')
        other = Project.objects.create(name='Other')
        dataset = Dataset.objects.create(project=other, name='Other data', source_name='fixture', headers=[], schema_snapshot=[])
        foreign = RobotRun.objects.create(dataset=dataset, robot_name='OTHER', heartbeat=timezone.now(), active_slot=None)
        for value in [str(foreign.pk), 'not-a-uuid']:
            self.assertEqual(self.client.get(reverse('robot-detail', args=[self.robot.pk]), {'run':value}).status_code, 404)

    def test_build_source_is_escaped_and_versions_are_scoped(self):
        response = self.client.get(reverse('robot-build-detail', args=[self.robot.pk, 1]))
        self.assertContains(response, '&lt;script&gt;do_not_execute()&lt;/script&gt;')
        self.assertNotContains(response, '<script>do_not_execute()</script>')
        self.assertEqual(self.client.get(reverse('robot-build-detail', args=[self.robot.pk, 2])).status_code, 404)

    def test_directory_deduplicates_completed_rows_across_attempts(self):
        self.attempt(0, 'OK', True)
        previous = RobotRun.objects.create(dataset=self.dataset, robot_name=self.robot.name, heartbeat=timezone.now(), active_slot=None)
        RowAttempt.objects.create(run=previous, row=self.rows[0], outcome='OK')
        self.rows[0].processing_status = 'done'
        self.rows[0].save()
        response = self.client.get(reverse('robot-list'))
        entry = next(robot for robot in response.context['page'] if robot.pk == self.robot.pk)
        self.assertEqual(entry.completed_count, 1)
        self.assertEqual(entry.pending_count, 3)
        self.assertContains(response, self.robot.name)
        self.assertContains(self.client.get(reverse('home')), 'href="/robots/"')

    def test_row_results_paginate_and_escape_input(self):
        for index in range(26):
            row = DatasetRow.objects.create(dataset=self.dataset, row_number=100 + index, values={'name':f'unique-{index}'})
            RowAttempt.objects.create(run=self.run, row=row, outcome='OK')
        response = self.client.get(reverse('robot-detail', args=[self.robot.pk]))
        self.assertContains(response, 'unique-24')
        self.assertNotContains(response, 'unique-25')
        response = self.client.get(reverse('robot-detail', args=[self.robot.pk]), {'rows_page':2})
        self.assertContains(response, 'unique-25')
        self.assertNotContains(response, 'unique-0')

    def test_cross_project_build_cannot_be_executed(self):
        other = Project.objects.create(name='Other')
        robot = Robot.objects.create(project=other, name='OTHER')
        build = RobotBuild.objects.create(robot=robot, version=1, origin='manual', status='registered')
        with self.assertRaises(ValueError):
            create_run(self.dataset, self.robot.name, build=build)

    def test_timestamps_persist_at_lifecycle_boundaries(self):
        run = create_run(self.dataset, self.robot.name, build=self.build)
        queue = DjangoQueue(run)
        queue.emit('run_started')
        queue.emit('row_started', row=str(self.rows[0].pk))
        from robot_framework.contracts import RowResult, Outcome, RunResult, RunState
        result = RowResult(str(self.rows[0].pk), Outcome.OK)
        queue.emit('row_finished', row=result.reference, result=result)
        queue.emit('run_completed', summary=RunResult(state=RunState.COMPLETED, rows=[result]))
        run.refresh_from_db()
        self.assertIsNotNone(run.started_at)
        self.assertGreaterEqual(run.finished_at, run.started_at)
        attempt = run.attempts.get()
        self.assertGreaterEqual(attempt.finished_at, attempt.started_at)

    def test_backfill_uses_events_and_does_not_assign_todays_build(self):
        self.run.build = None
        self.run.started_at = self.run.finished_at = None
        self.run.save()
        attempt = self.attempt(0, 'OK')
        for kind, row in [('run_started', ''), ('row_started', str(self.rows[0].pk)),
                          ('row_finished', str(self.rows[0].pk)), ('run_completed', '')]:
            ProgressEvent.objects.create(run=self.run, kind=kind, row_reference=row)
        migration = importlib.import_module('execution.migrations.0004_backfill_robot_history')
        migration.backfill(apps, None)
        self.run.refresh_from_db()
        attempt.refresh_from_db()
        self.assertIsNone(self.run.build)
        self.assertIsNotNone(self.run.started_at)
        self.assertIsNotNone(self.run.finished_at)
        self.assertIsNotNone(attempt.started_at)
        self.assertIsNotNone(attempt.finished_at)


class ManualBuildTests(TestCase):
    def test_registration_is_versioned_and_previous_runs_keep_their_build(self):
        call_command('prepare_robot_demo', stdout=StringIO())
        project = Project.objects.get(name='Invoice Checks')
        first = register_manual_build(project, 'ROBOT_INVOICE_CHECKS')
        again = register_manual_build(project, 'ROBOT_INVOICE_CHECKS')
        self.assertEqual(first.pk, again.pk)
        self.assertIn('robots/example_robot.py', first.source_files)
        dataset = project.datasets.get()
        run = create_run(dataset, 'ROBOT_INVOICE_CHECKS', build=first)
        element = project.windows.get().elements.get(name='name')
        old_config = first.configuration
        element.locator = {'strategy':'css', 'value':'#renamed-input'}
        element.save()
        second = register_manual_build(project, 'ROBOT_INVOICE_CHECKS')
        self.assertEqual(second.version, 2)
        first.refresh_from_db()
        run.refresh_from_db()
        self.assertEqual(first.configuration, old_config)
        self.assertEqual(run.build_id, first.pk)
        self.assertNotEqual(first.source_digest, second.source_digest)
