from pathlib import Path
from tempfile import TemporaryDirectory

from django.test import TestCase, override_settings
from django.urls import reverse
from django.utils import timezone

from projects.models import Project, Dataset
from .models import RobotRun


class RecordingTests(TestCase):
    def setUp(self):
        self.temp = TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.settings_override = override_settings(MEDIA_ROOT=self.temp.name)
        self.settings_override.enable()
        self.addCleanup(self.settings_override.disable)
        project = Project.objects.create(name='Recording fixture')
        dataset = Dataset.objects.create(project=project, name='Fixture', headers=[], schema_snapshot=[])
        self.run = RobotRun.objects.create(dataset=dataset, robot_name='ROBOT_FIXTURE',
            heartbeat=timezone.now(), active_slot=None, state='completed', is_test=True,
            test_options={'planned_rows': 10, 'record_screen': True}, outputs={'congrats': 'Congratulations!'})
        self.folder = Path(self.temp.name) / 'runs' / str(self.run.pk)
        self.folder.mkdir(parents=True)
        self.video = self.folder / 'page.webm'
        self.video.write_bytes(b'fixture-video')
        self.run.artifacts = [str(self.video)]
        self.run.save()
        self.url = reverse('run-recording', args=[self.run.pk, 0])

    def test_play_and_download_only_registered_video(self):
        response = self.client.get(self.url)
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response['Content-Type'], 'video/webm')
        self.assertEqual(b''.join(response.streaming_content), b'fixture-video')
        response.close()
        response = self.client.get(self.url + '?download=1')
        self.assertIn('attachment;', response['Content-Disposition'])
        response.close()
        self.assertEqual(self.client.get(reverse('run-recording', args=[self.run.pk, 1])).status_code, 404)

    def test_other_run_paths_and_non_video_are_rejected(self):
        for path in [Path(self.temp.name) / 'secret.webm', self.folder / 'secret.txt', self.folder / '..' / 'outside.webm']:
            path.write_bytes(b'private')
            self.run.artifacts = [str(path)]
            self.run.save()
            self.assertEqual(self.client.get(self.url).status_code, 404)

    def test_active_and_missing_recordings_are_unavailable(self):
        self.run.active_slot = 'local'
        self.run.save()
        self.assertEqual(self.client.get(self.url).status_code, 404)
        self.run.active_slot = None
        self.run.save()
        self.video.unlink()
        self.assertEqual(self.client.get(self.url).status_code, 404)
        response = self.client.get(reverse('run-detail', args=[self.run.pk]))
        self.assertContains(response, 'unavailable on this machine')

    def test_results_expose_playback_outputs_and_remaining(self):
        response = self.client.get(reverse('run-detail', args=[self.run.pk]))
        self.assertContains(response, 'Watch recording')
        self.assertContains(response, self.url)
        self.assertContains(response, 'Congratulations!')
        self.assertEqual(response.context['remaining_count'], 10)
        self.assertEqual(response.context['treated_count'], 0)
        self.run.artifacts = []
        self.run.test_options = {'record_screen': False}
        self.run.save()
        self.assertContains(self.client.get(reverse('run-detail', args=[self.run.pk])), 'No recording saved.')
