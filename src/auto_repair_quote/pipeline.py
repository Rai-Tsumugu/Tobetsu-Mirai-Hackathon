"""Authoritative band-preserving quote pipeline."""
from copy import deepcopy
from decimal import Decimal
from uuid import uuid4
from .common import BANDS, new_quote
from . import p01, p02, p03, p04, p05, p06, p07


def json_ready(value):
    if isinstance(value, Decimal):
        return int(value) if value == value.to_integral_value() else float(value)
    if isinstance(value, dict):
        return {key: json_ready(item) for key, item in value.items()}
    if isinstance(value, (list, tuple)):
        return [json_ready(item) for item in value]
    return value


def calculate(inputs):
    if not isinstance(inputs, dict):
        raise ValueError('inputs must be an object')
    inputs = deepcopy(inputs)
    # Validate the supplied shapes through P03 before dereferencing their fields.
    quote = new_quote({}, {}, [])
    quote.update(quote_id=inputs.get('quote_id') or 'Q-'+uuid4().hex[:10],
                 quote_version=inputs.get('quote_version', 1), customer_ref=inputs.get('customer_ref'),
                 vehicle_ref=inputs.get('vehicle_ref'), job_ref=inputs.get('job_ref'),
                 selected_band=None, conditions=[], fictional=isinstance(inputs.get('items'), list)
                 and all(isinstance(item, dict) and item.get('source') == 'simulator'
                         for item in inputs.get('items', [])))
    quote['metadata']['input_snapshot'] = deepcopy(inputs)
    if inputs.get('parent_version') is not None:
        quote['parent_version'] = inputs['parent_version']
    quote = p03.apply(quote, inputs)
    if quote['status'] == 'blocked':
        for field in ('subtotal', 'tax', 'total'):
            quote[field] = {band: None for band in BANDS}
        return json_ready(quote)
    try:
        quote = p01.apply(quote, inputs)
        if inputs.get('labor', {}).get('breakdown'):
            quote = p02.apply(quote, inputs)
        quote = p04.apply(quote, inputs)
        quote = p07.apply(quote, inputs)
        if inputs.get("discount") is not None:
            quote = p05.apply(quote, inputs)
        quote = p06.apply(quote, inputs)
        quote = p07.apply(quote, inputs)
        from . import p08, p09, p10, p11
        quote = p09.apply(quote, inputs)
        quote = p11.apply(quote, inputs)
        quote = p10.apply(quote, inputs)
        quote = p08.apply(quote)
    except (ValueError, TypeError, KeyError) as error:
        quote.update(status='blocked', issues=[{'code':'calculation_blocked','path':'inputs','message':str(error)}])
        for field in ('subtotal', 'tax', 'total'):
            quote[field] = {band: None for band in BANDS}
    return json_ready(quote)
