from django.db import migrations


def backfill(apps, schema_editor):
    Robot = apps.get_model('execution', 'Robot')
    Run = apps.get_model('execution', 'RobotRun')
    Attempt = apps.get_model('execution', 'RowAttempt')
    Event = apps.get_model('execution', 'ProgressEvent')
    for run in Run.objects.order_by('-created_at').iterator():
        Robot.objects.get_or_create(project_id=run.dataset.project_id, defaults={'name':run.robot_name})
        events = list(Event.objects.filter(run_id=run.pk).order_by('pk').values('kind', 'row_reference', 'created_at'))
        start = next((event['created_at'] for event in events if event['kind'] == 'run_started'), None)
        finish = next((event['created_at'] for event in reversed(events) if event['kind'] in ['run_completed', 'run_failed', 'run_cancelled']), None)
        Run.objects.filter(pk=run.pk).update(started_at=start, finished_at=finish)
        for attempt in Attempt.objects.filter(run_id=run.pk):
            row_events = [event for event in events if event['row_reference'] == str(attempt.row_id)]
            row_start = next((event['created_at'] for event in row_events if event['kind'] == 'row_started'), None)
            row_finish = next((event['created_at'] for event in reversed(row_events) if event['kind'] == 'row_finished'), None)
            Attempt.objects.filter(pk=attempt.pk).update(started_at=row_start, finished_at=row_finish)
    # Older runs deliberately retain build=None: today's source cannot identify
    # which code was executed historically. Missing timestamps are not estimated.


class Migration(migrations.Migration):
    dependencies = [('execution', '0003_robotrun_finished_at_robotrun_started_at_and_more')]
    operations = [migrations.RunPython(backfill, migrations.RunPython.noop)]
