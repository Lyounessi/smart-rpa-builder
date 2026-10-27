from django.contrib.auth import get_user_model
from django.test import TestCase
from django.urls import reverse
from django.core.exceptions import ValidationError

from inspector.models import ApplicationWindow, CapturedElement
from .models import Project, WorkflowStep, StepElementReference
from .services import move_step


class FoundationTests(TestCase):
    def test_custom_user_can_be_created(self):
        user = get_user_model().objects.create_user(username="builder", password="example-test-password")
        self.assertEqual(user._meta.label, "accounts.User")
        self.assertTrue(user.check_password("example-test-password"))

    def test_home_uses_local_htmx(self):
        response = self.client.get(reverse("home"))
        self.assertContains(response, '/static/vendor/htmx.min.js')
        self.assertContains(response, 'hx-get="/status/"')

    def test_status_returns_html_fragment(self):
        response = self.client.get(reverse("status"), HTTP_HX_REQUEST="true")
        self.assertContains(response, "Platform ready")
        self.assertNotContains(response, "<!doctype")
        self.assertEqual(self.client.post(reverse("status")).status_code, 405)


class WorkflowEditorTests(TestCase):
    def setUp(self):
        self.project = Project.objects.create(name="Create supplier")
        self.other = Project.objects.create(name="Other project")
        self.window = ApplicationWindow.objects.create(project=self.project, name="Supplier portal", target_url="https://example.com/suppliers")
        self.other_window = ApplicationWindow.objects.create(project=self.other, name="Other portal", target_url="https://example.org")
        self.element = CapturedElement.objects.create(window=self.window, name="Supplier name", locator={"strategy": "role", "role": "textbox", "name": "Supplier name"})
        self.foreign_element = CapturedElement.objects.create(window=self.other_window, name="Foreign element", locator={"strategy": "label", "value": "Name"})

    def add_step(self, **overrides):
        data = {"name": "Enter supplier", "instruction": "Fill using supplier_name", "window": self.window.pk, "target": ""}
        data.update(overrides)
        return self.client.post(reverse("step-create", args=[self.project.pk]), data)

    def test_end_to_end_editor_persists_and_reloads(self):
        response = self.client.post(reverse("project-create"), {"name": "Invoice approval", "description": "Daily workflow", "application_scope": "web"})
        project = Project.objects.get(name="Invoice approval")
        self.assertRedirects(response, reverse("project-detail", args=[project.pk]))
        response = self.client.post(reverse("window-create", args=[project.pk]), {"name": "Invoices", "target_url": "https://example.com/invoices"})
        self.assertEqual(response.status_code, 302)
        window = project.windows.get()
        self.client.post(reverse("step-create", args=[project.pk]), {"name": "Open invoices", "instruction": "Navigate to invoices", "window": window.pk})
        response = self.client.get(reverse("project-detail", args=[project.pk]))
        self.assertContains(response, "Open invoices")
        self.assertContains(response, "https://example.com/invoices")
        self.assertEqual(project.steps.get().position, 1)
        self.assertFalse(project.steps.get().element_references.exists())

    def test_step_can_have_no_window_or_target(self):
        self.assertEqual(self.add_step(window="").status_code, 302)
        self.assertIsNone(self.project.steps.get().window)

    def test_target_is_saved_for_selected_window(self):
        self.assertEqual(self.add_step(target=str(self.element.pk)).status_code, 302)
        step = self.project.steps.get()
        self.assertEqual(step.window, self.window)
        self.assertEqual(step.element_references.get().element, self.element)

    def test_rejects_foreign_application_and_target(self):
        for data in [{"window": self.other_window.pk}, {"target": str(self.foreign_element.pk)}]:
            response = self.add_step(**data)
            self.assertEqual(response.status_code, 200)
            self.assertContains(response, "Select a valid choice")
        self.assertFalse(self.project.steps.exists())

    def test_rejects_target_from_different_window_in_same_project(self):
        another = ApplicationWindow.objects.create(project=self.project, name="Reports", target_url="https://example.com/reports")
        response = self.add_step(window=another.pk, target=str(self.element.pk))
        self.assertContains(response, "Select a valid choice")
        self.assertFalse(self.project.steps.exists())

    def test_target_choices_follow_selected_application(self):
        another = ApplicationWindow.objects.create(project=self.project, name="Reports", target_url="https://example.com/reports")
        other_element = CapturedElement.objects.create(window=another, name="Report field", locator={"strategy":"label", "value":"Report"})
        url = reverse("step-target-options", args=[self.project.pk])
        response = self.client.get(url, {"window": self.window.pk})
        self.assertContains(response, str(self.element.pk))
        self.assertNotContains(response, str(other_element.pk))
        self.assertNotContains(response, str(self.foreign_element.pk))
        for invalid in ["", "invalid", self.other_window.pk]:
            response = self.client.get(url, {"window": invalid})
            self.assertEqual(response.status_code, 200)
            self.assertNotContains(response, str(self.element.pk))
            self.assertNotContains(response, str(self.foreign_element.pk))
        self.assertContains(self.client.get(reverse("step-create", args=[self.project.pk])), "Choose a target application first")

    def test_edit_target_choices_are_filtered_before_any_change(self):
        self.add_step(target=str(self.element.pk))
        step = self.project.steps.get()
        response = self.client.get(reverse("step-edit", args=[self.project.pk, step.pk]))
        self.assertContains(response, str(self.element.pk))
        self.assertNotContains(response, str(self.foreign_element.pk))
        self.assertContains(response, 'hx-target="#id_target"')

    def test_target_without_application_is_rejected(self):
        response = self.add_step(window="", target=str(self.element.pk))
        self.assertContains(response, "Select a valid choice")
        self.assertFalse(self.project.steps.exists())

    def test_model_rejects_cross_project_reference(self):
        self.add_step()
        with self.assertRaises(ValidationError):
            StepElementReference.objects.create(step=self.project.steps.get(), element=self.foreign_element)

    def test_nested_edit_routes_are_project_scoped(self):
        self.assertEqual(self.client.get(reverse("window-edit", args=[self.project.pk, self.other_window.pk])).status_code, 404)
        step = WorkflowStep.objects.create(project=self.other, position=1, name="Other", instruction="Other")
        self.assertEqual(self.client.get(reverse("step-edit", args=[self.project.pk, step.pk])).status_code, 404)
        self.assertEqual(self.client.post(reverse("step-move", args=[self.project.pk, step.pk]), {"direction": "up"}).status_code, 404)

    def test_reorder_and_append_preserve_positions(self):
        for name in ["First", "Second", "Third"]:
            self.add_step(name=name)
        second = self.project.steps.get(name="Second")
        response = self.client.post(reverse("step-move", args=[self.project.pk, second.pk]), {"direction": "up"}, HTTP_HX_REQUEST="true")
        self.assertContains(response, 'id="steps"')
        self.assertNotContains(response, "<!doctype")
        self.assertEqual(list(self.project.steps.values_list("name", "position")), [("Second", 1), ("First", 2), ("Third", 3)])
        move_step(second, "up")
        self.add_step(name="Fourth")
        self.assertEqual(list(self.project.steps.values_list("position", flat=True)), [1, 2, 3, 4])

    def test_edit_replaces_reference_and_removal_is_optional(self):
        self.add_step(target=str(self.element.pk))
        step = self.project.steps.get()
        url = reverse("step-edit", args=[self.project.pk, step.pk])
        self.assertContains(self.client.get(url), str(self.element.pk))
        response = self.client.post(url, {"name": "Navigate", "instruction": "Open supplier page", "window": self.window.pk, "target": ""})
        self.assertEqual(response.status_code, 302)
        self.assertFalse(step.element_references.exists())
        step.refresh_from_db()
        self.assertEqual(step.position, 1)

    def test_htmx_form_validation_and_save(self):
        url = reverse("project-create")
        response = self.client.get(url, HTTP_HX_REQUEST="true")
        self.assertContains(response, "csrfmiddlewaretoken")
        self.assertNotContains(response, "<!doctype")
        response = self.client.post(url, {"name": ""}, HTTP_HX_REQUEST="true")
        self.assertContains(response, "This field is required")
        response = self.client.post(url, {"name": "HTMX project", "application_scope": "web"}, HTTP_HX_REQUEST="true")
        self.assertEqual(response.headers["HX-Redirect"], reverse("project-detail", args=[Project.objects.get(name="HTMX project").pk]))

    def test_url_rejects_credentials_and_non_web_schemes(self):
        for url in ["ftp://example.com", "https://user:password@example.com"]:
            response = self.client.post(reverse("window-create", args=[self.project.pk]), {"name": "Unsafe", "target_url": url})
            self.assertContains(response, "Use an HTTP(S) URL without embedded credentials")
        self.assertEqual(self.project.windows.count(), 1)

    def test_mutations_require_post_and_csrf(self):
        from django.test import Client
        self.add_step()
        url = reverse("step-move", args=[self.project.pk, self.project.steps.get().pk])
        self.assertEqual(self.client.get(url).status_code, 405)
        self.assertEqual(Client(enforce_csrf_checks=True).post(url, {"direction": "up"}).status_code, 403)
        self.assertEqual(self.client.post(url, {"direction": "invalid"}).status_code, 400)

    def test_project_application_setup_is_saved_and_editable(self):
        response = self.client.post(reverse("project-create"), {"name": "Cross-site workflow", "application_scope": "multiple"})
        project = Project.objects.get(name="Cross-site workflow")
        self.assertEqual(project.application_scope, "multiple")
        self.assertRedirects(response, reverse("project-detail", args=[project.pk]))
        self.assertContains(self.client.get(reverse("project-detail", args=[project.pk])), "Web only for now")
        self.client.post(reverse("project-edit", args=[project.pk]), {"name": project.name, "application_scope": "web"})
        project.refresh_from_db()
        self.assertEqual(project.application_scope, "web")

    def test_desktop_setup_is_disabled_and_rejected_on_server(self):
        response = self.client.get(reverse("project-create"))
        self.assertContains(response, '<option value="desktop" disabled>')
        self.assertContains(response, "Multiple applications — web only for now")
        response = self.client.post(reverse("project-create"), {"name": "Desktop test", "application_scope": "desktop"})
        self.assertContains(response, "Desktop projects are coming later")
        self.assertFalse(Project.objects.filter(name="Desktop test").exists())
