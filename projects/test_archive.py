from django.test import TestCase
from django.urls import reverse
from django.utils import timezone

from projects.models import Project, Dataset, DatasetRow
from execution.models import Robot, RobotRun
from execution.adapters import create_run


class ProjectArchiveTests(TestCase):
    def setUp(self):
        self.project=Project.objects.create(name='Archive fixture')
        self.robot=Robot.objects.create(project=self.project,name='ROBOT_ARCHIVE_FIXTURE')
        self.dataset=Dataset.objects.create(project=self.project,name='Records',headers=[],schema_snapshot=[],status='ready')
        DatasetRow.objects.create(dataset=self.dataset,row_number=1,values={})
        self.url=reverse('project-archive',args=[self.project.pk])

    def test_archive_hides_project_and_robot_and_restore_preserves_data(self):
        self.assertEqual(self.client.get(self.url).status_code,405)
        self.assertEqual(self.client.post(self.url,{'action':'archive'}).status_code,302)
        self.assertNotContains(self.client.get(reverse('home')),self.project.name)
        self.assertNotContains(self.client.get(reverse('robot-list')),self.robot.name)
        self.assertContains(self.client.get(reverse('home')+'?archived=1'),self.project.name)
        self.assertContains(self.client.get(reverse('project-detail',args=[self.project.pk])),'Restore project and robot')
        with self.assertRaisesMessage(ValueError,'Restore the archived project'):
            create_run(self.dataset,self.robot.name)
        self.assertEqual(self.client.post(self.url,{'action':'restore'}).status_code,302)
        self.assertContains(self.client.get(reverse('home')),self.project.name)
        self.assertContains(self.client.get(reverse('robot-list')),self.robot.name)
        self.assertEqual(self.dataset.rows.count(),1)

    def test_active_run_prevents_archive_and_history_is_preserved(self):
        run=RobotRun.objects.create(dataset=self.dataset,robot_name=self.robot.name,heartbeat=timezone.now())
        self.assertEqual(self.client.post(self.url,{'action':'archive'}).status_code,400)
        self.project.refresh_from_db()
        self.assertIsNone(self.project.archived_at)
        run.active_slot=None
        run.state='completed'
        run.save()
        self.client.post(self.url,{'action':'archive'})
        self.assertTrue(RobotRun.objects.filter(pk=run.pk).exists())
