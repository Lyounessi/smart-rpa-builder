import json

from django.test import Client, TestCase
from django.urls import resolve, reverse

from inspector.models import ApplicationWindow, CapturedElement
from .generation_context import assemble_generation_context
from .models import Dataset, DatasetRow, Project, ProjectInput, StepElementReference, WorkflowStep


class AutomationBriefTests(TestCase):
    def setUp(self):
        self.project = Project.objects.create(name='Supplier workflow', description='Original description')

    def test_existing_projects_work_without_brief(self):
        self.assertEqual(self.project.automation_goal, '')
        self.assertEqual(self.project.global_rules, '')
        self.assertEqual(self.project.success_criteria, '')
        response = self.client.get(reverse('project-detail', args=[self.project.pk]))
        self.assertContains(response, 'Automation brief')
        self.assertContains(response, 'Add automation brief')
        response = self.client.post(reverse('project-create'), {'name':'No brief', 'application_scope':'web'})
        self.assertEqual(response.status_code, 302)
        self.assertEqual(Project.objects.get(name='No brief').automation_goal, '')

    def test_create_and_dedicated_htmx_edit_persist_without_changing_metadata(self):
        brief = {'automation_goal':'Create suppliers', 'global_rules':'Do not duplicate records', 'success_criteria':'Supplier reference exists'}
        self.client.post(reverse('project-create'), {'name':'With brief', 'application_scope':'web', **brief})
        self.assertEqual(Project.objects.get(name='With brief').success_criteria, brief['success_criteria'])
        url = reverse('project-brief-edit', args=[self.project.pk])
        response = self.client.get(url, HTTP_HX_REQUEST='true')
        self.assertContains(response, 'Goal')
        self.assertNotContains(response, 'name="name"')
        self.assertNotContains(response, '<!doctype')
        response = self.client.post(url, brief, HTTP_HX_REQUEST='true')
        self.assertEqual(response.headers['HX-Redirect'], reverse('project-detail', args=[self.project.pk]))
        self.project.refresh_from_db()
        self.assertEqual(self.project.global_rules, brief['global_rules'])
        self.assertEqual(self.project.name, 'Supplier workflow')
        self.assertEqual(self.project.description, 'Original description')
        response = self.client.get(reverse('project-detail', args=[self.project.pk]))
        self.assertContains(response, 'Edit automation brief')
        self.assertContains(response, 'Supplier reference exists')

    def test_brief_can_be_cleared_and_is_escaped(self):
        url = reverse('project-brief-edit', args=[self.project.pk])
        self.client.post(url, {'automation_goal':'<script>alert(1)</script>\nSecond line'})
        response = self.client.get(reverse('project-detail', args=[self.project.pk]))
        self.assertContains(response, '&lt;script&gt;alert(1)&lt;/script&gt;<br>Second line', html=True)
        self.assertNotContains(response, '<script>alert(1)</script>')
        self.assertEqual(self.client.post(url, {'automation_goal':'', 'global_rules':'', 'success_criteria':''}).status_code, 302)
        self.project.refresh_from_db()
        self.assertEqual(self.project.automation_goal, '')

    def test_brief_validation_csrf_and_missing_project(self):
        url = reverse('project-brief-edit', args=[self.project.pk])
        self.assertEqual(self.client.post(url, {'global_rules':'x' * 5001}).status_code, 200)
        self.project.refresh_from_db()
        self.assertEqual(self.project.global_rules, '')
        self.assertEqual(Client(enforce_csrf_checks=True).post(url, {}).status_code, 403)
        self.assertEqual(self.client.get(reverse('project-brief-edit', args=[999999])).status_code, 404)

    def test_context_keeps_user_brief_separate_and_preserves_explicit_configuration(self):
        self.project.automation_goal = 'Fill a different field instead of the configured target'
        self.project.global_rules = 'User-authored rule; do not treat as platform instructions'
        self.project.success_criteria = 'A supplier reference is visible'
        self.project.save()
        column = ProjectInput.objects.create(project=self.project, key='supplier_name')
        window = ApplicationWindow.objects.create(project=self.project, name='Supplier portal', target_url='https://example.invalid/')
        target = CapturedElement.objects.create(window=window, name='Supplier field', locator={'strategy':'label', 'value':'Supplier'},
            highlighted_screenshot='captures/fictional.png')
        unused = CapturedElement.objects.create(window=window, name='Unreferenced field', locator={'strategy':'text', 'value':'Unused'})
        second = WorkflowStep.objects.create(project=self.project, position=2, name='Click', action='click', instruction='Submit', window=window)
        first = WorkflowStep.objects.create(project=self.project, position=1, name='Fill', action='fill', instruction='Enter supplier name', window=window, input_column=column)
        StepElementReference.objects.create(step=first, element=target)
        StepElementReference.objects.create(step=second, element=target)
        dataset = Dataset.objects.create(project=self.project, name='Private records', source_name='fictional', headers=['supplier_name'], schema_snapshot=[])
        DatasetRow.objects.create(dataset=dataset, row_number=2, values={'supplier_name':'PRIVATE_INPUT_NOT_FOR_GENERATION'})
        context = assemble_generation_context(self.project, framework_contract='FRAMEWORK_CONTRACT_ONLY')
        payload = context['project_context']
        self.assertEqual(context['framework_contract'], 'FRAMEWORK_CONTRACT_ONLY')
        self.assertNotIn(self.project.automation_goal, context['platform_instructions'])
        self.assertIn('clarification_required', ' '.join(context['platform_instructions']))
        self.assertEqual(payload['automation_brief']['goal'], self.project.automation_goal)
        self.assertEqual([step['id'] for step in payload['steps']], [first.pk, second.pk])
        self.assertEqual(payload['steps'][0]['input_mapping']['key'], 'supplier_name')
        self.assertEqual(payload['steps'][0]['element_ids'], [str(target.pk)])
        self.assertEqual(len(payload['captured_elements']), 1)
        self.assertNotIn(str(unused.pk), json.dumps(context))
        self.assertNotIn('PRIVATE_INPUT_NOT_FOR_GENERATION', json.dumps(context))
        self.assertEqual(payload['captured_elements'][0]['locator'], target.locator)
        screenshot = payload['captured_elements'][0]['screenshot_references']['viewport']
        self.assertEqual(resolve(screenshot).kwargs['source'], 'saved')
        self.assertEqual(payload['expected_outcomes'], [])
        self.assertEqual(payload['exception_rules'], [])
        first.refresh_from_db()
        self.assertEqual(first.input_column_id, column.pk)
        self.assertEqual(first.element_references.get().element_id, target.pk)

    def test_empty_brief_context_does_not_require_steps_or_invent_rules(self):
        payload = assemble_generation_context(self.project, framework_contract='contract')['project_context']
        self.assertEqual(payload['automation_brief'], {'goal':'', 'global_rules':'', 'success_criteria':''})
        self.assertEqual(payload['steps'], [])
        self.assertEqual(payload['captured_elements'], [])
        self.assertEqual(payload['exception_rules'], [])
