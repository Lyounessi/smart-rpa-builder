from unittest.mock import patch
from django.test import TestCase
from django.urls import reverse
from django.utils import timezone
from projects.models import Project, Dataset
from execution.models import RobotRun
from inspector.models import ApplicationWindow
from .navigation import next_action


class NextActionTests(TestCase):
    def setUp(self):
        self.project=Project.objects.create(name='Guided project')

    def test_setup_and_archived_actions(self):
        self.assertEqual(next_action(self.project)['label'],'Add target application')
        self.project.archived_at=timezone.now()
        self.project.save()
        response=self.client.get(reverse('project-detail',args=[self.project.pk]))
        self.assertContains(response,'Restore project and robot')
        self.assertContains(response,'Project actions')

    def test_active_run_and_failed_run_do_not_claim_success(self):
        dataset=Dataset.objects.create(project=self.project,name='Records',headers=[],schema_snapshot=[])
        run=RobotRun.objects.create(dataset=dataset,robot_name='ROBOT_FIXTURE',heartbeat=timezone.now())
        self.assertEqual(next_action(self.project)['label'],'View live progress')
        ApplicationWindow.objects.create(project=self.project,name='Website',target_url='https://example.com')
        run.state='failed'
        run.active_slot=None
        run.save()
        with patch('projects.navigation.workflow_requirements',return_value=[]):
            action=next_action(self.project)
        self.assertEqual(action['title'],'Review your latest run')
        self.assertEqual(action['label'],'View results')

    def test_workflow_last_inputs_grouped_and_existing_links_preserved(self):
        response=self.client.get(reverse('project-detail',args=[self.project.pk]))
        html=response.content.decode()
        self.assertGreater(html.index('<h2>Workflow steps'),html.index('id="automation-brief-title"'))
        self.assertLess(html.index('<h2>Input data'),html.index('id="automation-brief-title"'))
        self.assertContains(response,'Add step')
        self.assertContains(response,'Upload input file')
