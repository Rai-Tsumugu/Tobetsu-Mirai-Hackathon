"""Compose the selected ideas into one estimate-to-explanation workflow."""
from copy import deepcopy

from .common import QuoteError
from .pipeline import calculate, json_ready
from .p12 import customer_summary
from .p22 import question_guide
from .p23 import compare_bands
from .p30 import document_payload


def preview(inputs):
    """Calculate once, then derive every view from that same quote snapshot."""
    if not isinstance(inputs, dict):
        raise QuoteError('inputs must be an object')
    quote = calculate(inputs)
    questions = question_guide(inputs)
    # Calculation validates more than the input-shape gate (e.g. approved markup).
    if quote['status'] == 'blocked':
        questions['can_calculate'] = False
        questions['status'] = 'blocked'
        known_paths = {question['field'] for question in questions['questions']}
        for issue in quote.get('issues', []):
            if issue['path'] not in known_paths:
                questions['questions'].append({
                    'field': issue['path'], 'prompt': issue['message'],
                    'detail': issue['message'], 'status': 'unanswered',
                    'answer': None, 'source_ref': issue['path'],
                })
                known_paths.add(issue['path'])
    can_confirm = quote['status'] == 'proposed'
    return json_ready({
        'quote': quote,
        'summary': customer_summary(quote),
        'band_comparison': compare_bands(quote) if can_confirm else [],
        'questions': questions,
        'can_confirm': can_confirm,
        'next_action': 'select_band' if can_confirm else 'resolve_conditions',
    })


def saved_workflow(store, quote_id, quote_version=None):
    """Explain a persisted version without recalculating or mixing newer events."""
    with store.transaction():
        quote = store.get_quote(quote_id, quote_version)
        version = quote['quote_version']
        communications = [event for event in store.list_communications(quote_id)
                          if event['quote_version'] == version]
        changes = [event for event in store.list_change_events(quote_id)
                   if event['to_version'] == version]
    confirmed = quote['status'] == 'confirmed'
    return json_ready({
        'quote': deepcopy(quote),
        'summary': customer_summary(quote),
        'document': document_payload(quote) if confirmed else None,
        'communications': communications,
        'changes': changes,
        'next_action': ('review_history' if communications else 'explain_and_record')
                       if confirmed else 'select_band',
    })
