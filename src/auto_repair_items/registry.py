"""Discover the thirty isolated implementation modules."""
from importlib import import_module


def module_for(idea_id):
    if idea_id not in [f'M{number:02d}' for number in range(1, 31)]:
        raise ValueError('案IDが不正です')
    return import_module(f'auto_repair_items.{idea_id.lower()}')


def specifications():
    result = []
    for number in range(1, 31):
        idea_id = f'M{number:02d}'
        try:
            result.append(module_for(idea_id).SPEC)
        except ModuleNotFoundError as error:
            if error.name != f'auto_repair_items.{idea_id.lower()}':
                raise
    return result
