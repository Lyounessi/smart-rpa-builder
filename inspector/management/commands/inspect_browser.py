import asyncio
import io
import json
import math
import time
from datetime import timedelta
from pathlib import Path
from urllib.request import urlopen

from asgiref.sync import sync_to_async
from django.core.management.base import BaseCommand
from django.utils import timezone

from inspector.locators import resolve, safe_url, validate
from inspector.models import CapturedElement, InspectionCommand, InspectionSession
from inspector.services import finish_session, persist_draft
from inspector.quality import initial_quality, record_observation
from inspector.candidates import candidates


@sync_to_async
def session_data(session_id):
    session = InspectionSession.objects.select_related('window').get(pk=session_id)
    return {"url": session.window.target_url, "instance": session.server_instance, "active": session.active_slot is not None, "step_id":session.step_id, "step_name":session.step.name}


@sync_to_async
def update_session(session_id, **values):
    InspectionSession.objects.filter(pk=session_id).update(**values, heartbeat=timezone.now())


@sync_to_async
def next_command(session_id):
    command = InspectionCommand.objects.filter(session_id=session_id, status="pending").order_by('created_at', 'pk').first()
    if not command:
        return None
    if command.operation != 'stop' and command.created_at < timezone.now() - timedelta(seconds=30):
        command.status = 'failed'
        command.result = {'message':'Command expired. Please retry explicitly.'}
        command.save(update_fields=['status', 'result', 'updated_at'])
        InspectionSession.objects.filter(pk=session_id).update(message='Command expired. Please retry explicitly.')
        return None
    command.status = "running"
    command.save(update_fields=['status', 'updated_at'])
    locator = command.element.locator if command.element_id else None
    return {"id": command.pk, "operation": command.operation, "element_id": command.element_id, "locator": locator,
            "session_id": command.session_id, "quality": command.element.selector_quality if command.element_id else {}}


@sync_to_async
def complete_command(command, result=None, failed=False):
    InspectionCommand.objects.filter(pk=command['id']).update(status='failed' if failed else 'done', result=result or {})
    if command.get('element_id') and result:
        quality = record_observation(command.get('quality'), result, command['session_id'])
        CapturedElement.objects.filter(pk=command['element_id']).update(validation_result=result, validated_at=timezone.now(), selector_quality=quality)


def server_alive(url, instance):
    try:
        with urlopen(url, timeout=2) as response:
            return json.load(response).get('instance') == instance
    except Exception:
        return False


async def choose_locator(page, metadata):
    from playwright.async_api import Error as PlaywrightError
    for definition in candidates(metadata):
        try:
            target = resolve(page, definition)
            if await target.count() == 1 and await target.is_visible() and await target.evaluate('(el) => el === window.__smartRpa.selected()'):
                return definition
        except PlaywrightError:
            if page.is_closed():
                raise
    raise ValueError('No unique visible selector found using labels, semantic attributes, IDs, classes or parent context. Select the actual control or refine the page context. OCR is not implemented.')


async def capture(page, session_id, step_id=None):
    from PIL import Image
    metadata = await page.evaluate('() => window.__smartRpa.metadata()')
    if metadata.get('unsupported'):
        raise ValueError('Frames, canvas and embedded controls are unsupported in this MVP. OCR or visual targeting may be added later.')
    definition = await choose_locator(page, metadata)
    target = resolve(page, definition)
    result = await validate(page, definition)
    if result['status'] != 'unique':
        raise ValueError('The selected element changed. Please recapture it.')
    await target.scroll_into_view_if_needed(timeout=3000)
    bounds = await target.bounding_box()
    if not bounds or bounds['width'] < 1 or bounds['height'] < 1:
        raise ValueError('The selected element is not visible. Please recapture it.')
    await target.evaluate('(el) => window.__smartRpa.highlight(el)')
    await page.evaluate('() => window.__smartRpa.hideToolbar()')
    try:
        # Mask editable fields and unsupported embedded surfaces in the source screenshot.
        masks = page.locator('input,textarea,[contenteditable]:not([contenteditable="false"]),iframe,canvas,object,embed,video')
        viewport = await page.screenshot(mask=[masks], mask_color='#64748b', scale='css', timeout=5000)
    finally:
        await page.evaluate('() => window.__smartRpa.showToolbar()')
    image = Image.open(io.BytesIO(viewport))
    x, y = max(0, math.floor(bounds['x'])), max(0, math.floor(bounds['y']))
    right, bottom = min(image.width, math.ceil(bounds['x'] + bounds['width'])), min(image.height, math.ceil(bounds['y'] + bounds['height']))
    if right <= x or bottom <= y:
        raise ValueError('The selected element is outside the viewport.')
    buffer = io.BytesIO()
    image.crop((x, y, right, bottom)).save(buffer, format='PNG')
    coordinates = {'bounding_box':bounds, 'viewport':{'width':image.width, 'height':image.height}, 'unit':'CSS pixels', 'origin':'viewport'}
    quality = initial_quality(metadata, definition, await page.evaluate('() => window.__smartRpa.documentId'), session_id)
    await sync_to_async(persist_draft)(session_id, metadata, definition, result, safe_url(page.url), coordinates, viewport, buffer.getvalue(), step_id=step_id, selector_quality=quality)


class Command(BaseCommand):
    help = 'Own one visible local inspection browser until stopped or disconnected.'

    def add_arguments(self, parser):
        parser.add_argument('session_id')
        parser.add_argument('--server-url', required=True)

    def handle(self, *args, **options):
        asyncio.run(self.run_browser(options['session_id'], options['server_url']))

    async def run_browser(self, session_id, server_url):
        browser = None
        stopped_status, stopped_message = 'stopped', 'Inspector stopped. Browser closed.'
        try:
            from playwright.async_api import async_playwright
            data = await session_data(session_id)
            if not data['active']:
                return
            actions = asyncio.Queue()
            async with async_playwright() as playwright:
                browser = await playwright.chromium.launch(headless=False)
                context = await browser.new_context(viewport={'width':1280, 'height':800}, device_scale_factor=1, accept_downloads=False)
                page = await context.new_page()
                page.set_default_timeout(4000)

                async def binding(source, value):
                    if source['page'] == page and source['frame'] == page.main_frame and isinstance(value, dict):
                        if value.get('action') in {'select', 'cancel', 'capture', 'stop'}:
                            await actions.put(value['action'])

                await page.expose_binding('__smartRpaAction', binding)
                await page.add_init_script(path=str(Path(__file__).resolve().parents[2] / 'selection.js'))
                page.on('framenavigated', lambda frame: actions.put_nowait('navigated') if frame == page.main_frame else None)
                async def close_extra(extra):
                    if extra != page:
                        await extra.close()
                        await update_session(session_id, message='New tabs are unsupported. Navigate within the original tab.')
                context.on('page', close_extra)
                await page.goto(data['url'], wait_until='domcontentloaded', timeout=20000)
                await update_session(session_id, status='browsing', message='Browser open. Navigate or log in, then select an element.')
                last_health, failures = 0, 0
                selection_step_id = data['step_id']
                health_url = server_url.rstrip('/') + f'/inspector/health/{session_id}/'
                while browser.is_connected() and not page.is_closed():
                    if time.monotonic() - last_health >= 2:
                        alive = await asyncio.to_thread(server_alive, health_url, data['instance'])
                        failures = 0 if alive else failures + 1
                        last_health = time.monotonic()
                        if failures >= 3:
                            stopped_status, stopped_message = 'interrupted', 'Server disconnected or restarted. Reopen the browser to continue.'
                            break
                        await update_session(session_id)
                        current = await session_data(session_id)
                        if current['step_id'] != data['step_id']:
                            data['step_id'] = current['step_id']
                            await page.evaluate('(name) => window.__smartRpa?.message("Browsing — target step: " + name)', current['step_name'])
                    # Apply page/navigation events before later Django commands. Otherwise
                    # an initial navigation event can cancel a newly requested selection.
                    command = await next_command(session_id) if actions.empty() else None
                    action = command['operation'] if command else (await actions.get() if not actions.empty() else None)
                    if not action:
                        await asyncio.sleep(.15)
                        continue
                    try:
                        if action == 'stop':
                            if command:
                                await complete_command(command)
                            break
                        if action == 'select':
                            selection_step_id = (await session_data(session_id))['step_id']
                            await page.evaluate('() => window.__smartRpa.select()')
                            await update_session(session_id, status='selecting', message='Hover and click a target. Escape cancels selection.')
                        elif action == 'navigated':
                            await page.evaluate('() => window.__smartRpa?.cancel()')
                            await update_session(session_id, status='browsing', message='Page changed. Select an element when ready.')
                        elif action == 'cancel':
                            await page.evaluate('() => window.__smartRpa.cancel()')
                            await update_session(session_id, status='browsing', message='Selection cancelled. Browser remains open.')
                        elif action == 'capture':
                            await update_session(session_id, status='capturing', message='Capturing masked screenshots…')
                            await capture(page, session_id, selection_step_id)
                            await page.evaluate('() => window.__smartRpa.message("Captured — return to Smart RPA Builder to review and save")')
                            await update_session(session_id, status='browsing', message='Capture ready. Review and save below; the browser stays open.')
                        elif action == 'test':
                            await update_session(session_id, status='testing', message='Testing saved selector…')
                            result = await validate(page, command['locator'], command['quality'].get('baseline'))
                            if result['status'] == 'unique':
                                target = resolve(page, command['locator'])
                                await target.scroll_into_view_if_needed()
                                await target.evaluate('(el) => window.__smartRpa.highlight(el)')
                            else:
                                await page.evaluate('() => window.__smartRpa.cancel()')
                            await complete_command(command, result)
                            await update_session(session_id, status='browsing', message=result['message'])
                        if command and action != 'test':
                            await complete_command(command)
                    except Exception as error:
                        # Do not persist browser exception strings: they may contain page values or URLs.
                        message = str(error) if isinstance(error, ValueError) else 'Operation failed. The page may have changed; navigate to the target and try again.'
                        if command:
                            await complete_command(command, {'status':'error', 'message':message}, failed=True)
                        await update_session(session_id, status='browsing', message=message[:300])
                        if not page.is_closed():
                            try:
                                await page.evaluate('() => window.__smartRpa?.message("Capture unavailable — review the message in Smart RPA Builder")')
                            except Exception:
                                pass
                await browser.close()
                browser = None
        except Exception:
            stopped_status = 'error'
            stopped_message = 'Could not run the inspection browser. Install inspector requirements and Chromium, then check the target URL.'
        finally:
            if browser and browser.is_connected():
                await browser.close()
            await sync_to_async(finish_session)(session_id, stopped_status, stopped_message)
