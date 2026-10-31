import os
from pathlib import Path
from unittest import skipUnless
from unittest.mock import patch

from django.conf import settings
from django.contrib.staticfiles.testing import StaticLiveServerTestCase
from django.test import override_settings
from django.urls import reverse

from .test_guided_build import make_guided_project
from .models import BuildSession,BuildOperation,MuseRequest


@skipUnless(os.environ.get('RUN_BROWSER_TESTS')=='1','Opt-in guided build browser test')
@override_settings(MUSE_APIKEY='fictional-api-key',META_MODEL='muse-spark-1.3',MUSE_MAX_OUTPUT_TOKENS='4096')
class GuidedBuildBrowserTests(StaticLiveServerTestCase):
    def test_user_can_prepare_edit_confirm_without_api_and_see_generation_ready(self):
        from playwright.sync_api import sync_playwright
        project,steps=make_guided_project()
        url=self.live_server_url+reverse('muse-build',args=[project.pk])
        folder=Path(settings.MEDIA_ROOT)/'ui-preview'
        folder.mkdir(parents=True,exist_ok=True)
        with patch('muse_builder.client.MetaClient.request',side_effect=AssertionError('No paid request in UI test')):
            with sync_playwright() as playwright:
                browser=playwright.chromium.launch(headless=True)
                try:
                    page=browser.new_page(viewport={'width':1440,'height':1000})
                    page.goto(url)
                    page.get_by_role('button',name='Prepare my plan (no API call)',exact=True).click()
                    page.get_by_label('When to run Start',exact=False).select_option('setup')
                    page.get_by_label('When to run Submit',exact=False).select_option('per_row')
                    page.get_by_label('When to run Congratulations',exact=False).select_option('finalization')
                    self.assertEqual(page.get_by_label('When to run Name',exact=False).input_value(),'per_row')
                    page.get_by_label('Success criteria',exact=False).fill('After Submit wait for changed round OR final completion. After all rows save Congratulations.')
                    page.get_by_label('Known rejection handling',exact=False).fill('Stop on any known rejection; no automatic Submit retry.')
                    self.assertFalse(page.locator('[data-build-recovery]').is_visible())
                    page.get_by_label('Technical error policy',exact=False).select_option('false')
                    self.assertTrue(page.locator('[data-build-recovery]').is_visible())
                    page.get_by_label('Technical error policy',exact=False).select_option('true')
                    page.get_by_role('button',name='Save plan (no API call)',exact=True).click()
                    page.get_by_role('button',name='Confirm agreed specification',exact=True).click()
                    generate=page.get_by_role('button',name='Generate draft robot (paid API requests)',exact=True)
                    self.assertTrue(generate.is_enabled())
                    self.assertFalse(page.locator('.build-technical').evaluate('(el)=>el.open'))
                    page.screenshot(path=str(folder/'guided-build-desktop.png'),full_page=True)
                    page.set_viewport_size({'width':390,'height':844})
                    self.assertTrue(page.evaluate('document.documentElement.scrollWidth <= window.innerWidth'))
                    page.screenshot(path=str(folder/'guided-build-mobile.png'),full_page=True)
                finally:
                    browser.close()
        self.assertEqual(BuildSession.objects.count(),1)
        self.assertIsNotNone(BuildSession.objects.get().confirmed_at)
        self.assertFalse(BuildOperation.objects.exists())
        self.assertFalse(MuseRequest.objects.exists())
