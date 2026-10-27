from django.contrib.auth import get_user_model
from django.test import TestCase
from django.urls import reverse


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
