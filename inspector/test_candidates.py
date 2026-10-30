import asyncio
import os
from pathlib import Path
from unittest import skipUnless
from unittest.mock import patch

from django.test import SimpleTestCase

from .candidates import candidates,quoted
from .quality import fingerprint


class CandidateTests(SimpleTestCase):
    def test_semantic_framework_attribute_precedes_random_id_and_name(self):
        metadata={'tag':'input','role':'textbox','name':'','label':'',
            'attributes':{'id':'Ab3xY','name':'Ab3xY','ng-reflect-name':'labelFirstName','ng-reflect-model':'SECRET','value':'SECRET'}}
        result=candidates(metadata)
        self.assertEqual(result[0],{'strategy':'css','value':'input[ng-reflect-name="labelFirstName"]'})
        self.assertNotIn('SECRET',str(result))

    def test_test_id_remains_preferred_and_candidate_generation_is_bounded(self):
        metadata={'tag':'input','role':'textbox','name':'Name','label':'Name','attributes':{'data-testid':'name'},
            'classes':['ng-valid','ng-touched','field','primary','wide','entry','form-field','input'],
            'ancestors':[{'tag':'section','attributes':{'id':'shipping','data-testid':'shipping'},'classes':['panel'],'label':'Name'}]*3}
        result=candidates(metadata)
        self.assertEqual(result[0],{'strategy':'test_id','value':'name'})
        self.assertLessEqual(len(result),48)
        self.assertNotIn('ng-valid',str(result))
        self.assertNotIn('ng-touched',str(result))
        self.assertEqual(len(result),len({str(item) for item in result}))

    def test_css_strings_preserve_unicode_and_escape_quotes_and_controls(self):
        self.assertEqual(quoted('Rôle'),'"Rôle"')
        self.assertEqual(quoted('a"b'),'"a\\"b"')
        self.assertEqual(quoted('a\nb'),'"a\\a b"')

    def test_label_context_precedes_unique_classes_and_random_ids(self):
        metadata={'tag':'input','attributes':{'id':'Ab3xY','name':'Ab3xY'},
            'nearby_label':'First Name','classes':['unique-today'], 'ancestors':[]}
        result=candidates(metadata)
        self.assertEqual(result[0]['strategy'],'xpath')
        self.assertNotIn('Ab3xY',str(result))


@skipUnless(os.environ.get('RUN_BROWSER_TESTS')=='1','Opt-in inspector selector fallback checks')
class SelectorFallbackBrowserTests(SimpleTestCase):
    def test_rpa_style_fields_capture_shuffle_and_validate_without_input_values(self):
        asyncio.run(self.exercise())

    async def exercise(self):
        from playwright.async_api import async_playwright
        from .management.commands.inspect_browser import choose_locator,capture
        from .locators import validate
        async with async_playwright() as playwright:
            browser=await playwright.chromium.launch(headless=True)
            try:
                page=await browser.new_page()
                await page.expose_binding('__smartRpaAction',lambda source,value:None)
                async def load(html):
                    await page.goto('about:blank')
                    await page.set_content(html)
                    await page.add_script_tag(path=str(Path(__file__).parent/'selection.js'))
                await load('<div id="fields"><div><label>First Name</label><input id="Ab3xY" name="Ab3xY" ng-reflect-name="labelFirstName" ng-reflect-model="SECRET" value="SECRET" class="ng-valid ng-pristine"></div><div><label>Last Name</label><input id="CD4zW" ng-reflect-name="labelLastName"></div></div>')
                await page.evaluate('() => window.__smartRpa.select()')
                await page.locator('input[ng-reflect-name="labelFirstName"]').click()
                metadata=await page.evaluate('() => window.__smartRpa.metadata()')
                self.assertNotIn('SECRET',str(metadata))
                self.assertEqual(metadata['nearby_label'],'First Name')
                definition=await choose_locator(page,metadata)
                self.assertEqual(definition['value'],'input[ng-reflect-name="labelFirstName"]')
                with patch('inspector.management.commands.inspect_browser.persist_draft') as persist:
                    await capture(page,'fixture-session')
                self.assertEqual(persist.call_args.args[2],definition)
                baseline=fingerprint(metadata)
                await page.evaluate('''() => { const root=document.getElementById('fields'); root.prepend(root.lastElementChild); document.querySelectorAll('input').forEach((el,index)=>{el.id='changed-'+index;el.name=el.id;el.setAttribute('data-qa','new-marker-'+index);}); }''')
                result=await validate(page,definition,baseline)
                self.assertEqual(result['status'],'unique')
                self.assertTrue(result['identity_matches'])
                await load('<form onsubmit="document.body.dataset.submitted=1;return false"><input type="submit" value="Submit"></form>')
                await page.evaluate('() => window.__smartRpa.select()')
                await page.get_by_role('button',name='Submit',exact=True).click()
                definition=await choose_locator(page,await page.evaluate('() => window.__smartRpa.metadata()'))
                self.assertEqual(definition,{'strategy':'role','role':'button','name':'Submit'})
                self.assertIsNone(await page.locator('body').get_attribute('data-submitted'))
                # A unique class pair can identify an unlabelled control, but identity remains unverified.
                await load('<input class="entry primary"><input class="entry secondary"><input class="secondary primary">')
                await page.evaluate('() => window.__smartRpa.select()')
                await page.locator('input').first.click()
                metadata=await page.evaluate('() => window.__smartRpa.metadata()')
                definition=await choose_locator(page,metadata)
                self.assertIn('class~=',definition['value'])
                result=await validate(page,definition,fingerprint(metadata))
                self.assertEqual(result['status'],'unique')
                self.assertFalse(result['identity_matches'])
                await load('<section data-testid="shipping"><input class="field"></section><section data-testid="billing"><input class="field"></section>')
                await page.evaluate('() => window.__smartRpa.select()')
                await page.locator('input').first.click()
                definition=await choose_locator(page,await page.evaluate('() => window.__smartRpa.metadata()'))
                self.assertIn('shipping',definition['value'])
                await load('<div><label>First Name</label><input class="field"></div><div><label>Last Name</label><input class="field"></div>')
                await page.evaluate('() => window.__smartRpa.select()')
                await page.locator('input').first.click()
                definition=await choose_locator(page,await page.evaluate('() => window.__smartRpa.metadata()'))
                self.assertEqual(definition['strategy'],'xpath')
                self.assertIn('First Name',definition['value'])
                await load('<input class="field"><input class="field">')
                await page.evaluate('() => window.__smartRpa.select()')
                await page.locator('input').first.click()
                with self.assertRaises(ValueError):
                    await choose_locator(page,await page.evaluate('() => window.__smartRpa.metadata()'))
            finally:
                await browser.close()
