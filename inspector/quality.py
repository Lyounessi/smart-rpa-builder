"""Evidence about a locator, never a promise that it is permanently stable."""
import re


def assess_id(value):
    if not value:
        return {'assessment': 'absent', 'reason': 'No element ID.'}
    generated = (
        re.search(r'^:.*:$', value)
        or re.search(r'[0-9a-f]{8}-[0-9a-f-]{27,}', value, re.I)
        or re.search(r'\d{4,}', value)
        or re.search(r'(?:react|radix|ember|mui|headlessui)[-_:]?\d', value, re.I)
        or re.search(r'(?:^|[-_])[0-9a-f]{8,}(?:$|[-_])', value, re.I)
        or (re.fullmatch(r'[A-Za-z0-9]{4,10}', value) and re.search(r'[a-z]', value)
            and re.search(r'[A-Z]', value) and re.search(r'\d', value))
    )
    return {
        'assessment': 'suspected_generated' if generated else 'unverified',
        'reason': 'Generated or record-specific pattern; heuristic only.' if generated else 'No obvious generated pattern; stability has not been demonstrated.',
    }


def fingerprint(metadata):
    result={key: metadata.get(key, '') for key in ('tag', 'role', 'name', 'label')}
    if metadata.get('nearby_label'):
        result['nearby_label']=metadata['nearby_label']
    semantic={key:metadata.get('attributes',{}).get(key) for key in
        ['data-testid','data-qa','data-cy','data-test','data-automation-id','formcontrolname','ng-reflect-name']
        if metadata.get('attributes',{}).get(key)}
    if semantic:
        result['semantic_attributes']=semantic
    return result


def initial_quality(metadata, locator, document_id, session_id):
    return {
        'version': 1,
        'assessment': 'unverified',
        'message': 'Verified only at capture. Reopen or manually reload the page, then test again.',
        'strategy': locator['strategy'],
        'id': assess_id(metadata.get('attributes', {}).get('id')),
        'baseline': fingerprint(metadata),
        'captured_id': metadata.get('attributes', {}).get('id', ''),
        'observations': [{'document': document_id, 'session': str(session_id)}] if document_id else [],
    }


def record_observation(quality, result, session_id):
    quality = dict(quality or {})
    if not quality:
        return {'version': 1, 'assessment': 'unverified', 'message': 'Legacy capture: recapture to establish an identity baseline.'}
    if result.get('status') != 'unique':
        quality.update(assessment='needs_review', message='The latest test failed. Review the page and selector before using this target.')
        return quality
    if result.get('identity_matches') is not True:
        quality.update(assessment='unverified', message='A unique match alone does not verify the original element identity.')
        return quality
    if quality.get('captured_id') != result.get('observed_id', ''):
        quality['id'] = {'assessment': 'observed_changing', 'reason': 'The matched control has a different ID from its capture.'}
    observations = list(quality.get('observations', []))
    document = result.get('document_id')
    if document and not any(item['document'] == document for item in observations):
        observations.append({'document': document, 'session': str(session_id)})
    quality['observations'] = observations[-10:]
    repeated = len({item['document'] for item in observations}) >= 2
    quality.update(
        assessment='observed_across_documents' if repeated else 'unverified',
        message='Same semantic identity matched across page loads. This is evidence, not a stability guarantee.' if repeated else 'Matched again in the same page load. Reload or reopen manually for additional evidence.',
    )
    return quality
