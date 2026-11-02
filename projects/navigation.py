"""One suggested next action; execution validation remains authoritative."""
from django.urls import reverse
from execution.models import RobotRun
from muse_builder.planning import workflow_requirements


def next_action(project):
    def card(title, text, label, url):
        return dict(title=title, text=text, label=label, url=url)
    if project.archived_at:
        return card('Project archived', 'Restore this project and its robot to continue. History and recordings are preserved.', '', '')
    run = RobotRun.objects.filter(dataset__project=project).order_by('-created_at').first()
    if run and run.active_slot:
        return card('Your robot is running', 'Follow progress or request a stop.', 'View live progress', reverse('run-detail', args=[run.pk]))
    if not project.windows.exists():
        return card('Connect your target website', 'Add the application the robot will work with.', 'Add target application', reverse('window-create', args=[project.pk]))
    issues = workflow_requirements(project)
    if issues:
        issue = issues[0]
        return card('Prepare your workflow', issue['text'], 'Complete next step', issue['url'])
    if run and not run.active_slot:
        treated = run.attempts.filter(business_completed_at__isnull=False).count()
        # Older runs may only have an OK outcome as their success evidence.
        treated += run.attempts.filter(business_completed_at__isnull=True, outcome='OK').count()
        title = 'Latest run completed' if run.state == 'completed' else 'Review your latest run'
        return card(title, f'{treated} confirmed treatments · {run.dataset.name}. Review outcomes before running again.', 'View results', reverse('run-detail', args=[run.pk]))
    dataset = project.datasets.filter(status='ready', invalid_row_count=0, rows__processing_status='pending', rows__errors=[], rows__deleted_at__isnull=True).first()
    if not dataset:
        return card('Prepare input records', 'Upload or enter records, review validation, and confirm the dataset.', 'Open input data', '#input-data')
    robot = getattr(project, 'robot', None)
    if robot and robot.builds.filter(status='validated', is_draft=True, specification_snapshot__isnull=False).exists():
        return card('Review your robot before running', 'Choose its version and dataset. The run screen checks that they are current and compatible.', 'Review and run robot', reverse('robot-run', args=[robot.pk]))
    return card('Your workflow is ready for planning', 'Review step timing and success checks before generating a draft.', 'Build with Muse', reverse('muse-build', args=[project.pk]))
