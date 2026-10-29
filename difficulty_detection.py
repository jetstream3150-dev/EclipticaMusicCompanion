"""Infer ECLIPTICA's named progress band from stage and boss log messages.

The names are an unofficial community convention, not a world API guarantee.
Only complete stage/boss records with a finite progress value in [0, 1] count.
"""
import math
import re


_EVENT = re.compile(
    r'ECLIPTICA - now (?P<kind>in stage|fighting boss):\s*'
    r'(?P<name>.+?)\s+on phase:\s*'
    r'(?P<progress>[+-]?(?:\d+(?:\.\d*)?|\.\d+)(?:[eE][+-]?\d+)?)'
    r'(?=\s|$)', re.IGNORECASE)


def infer_difficulty(line, previous=None):
    match = _EVENT.search(line)
    if not match:
        return None
    progress = float(match.group('progress'))
    if not math.isfinite(progress) or not 0 <= progress <= 1:
        return None
    kind = 'stage' if match.group('kind').lower() == 'in stage' else 'boss'
    name = re.sub(r'\(Clone\)$', '', match.group('name').strip(), flags=re.I).strip()
    slug = re.sub(r'[^a-z0-9]', '', name.casefold())
    final_stage = kind == 'stage' and slug == 'stagebringer' and progress == 1
    final_boss = kind == 'boss' and bool(re.fullmatch(r'jimbringer(?:phase\d+)?', slug))
    # Some final-boss form announcements repeat phase 0. Retain the final
    # stage only if this session already observed the final marker.
    previous_final = bool(previous and previous.get('final_stage'))
    if final_boss and progress == 0 and not previous_final:
        return None
    final = final_stage or (final_boss and (progress == 1 or (progress == 0 and previous_final)))
    if final:
        difficulty = 'Eye of the Eclipse'
    elif progress < .2:
        difficulty = 'Primal'
    elif progress < .4:
        difficulty = 'Penumbra'
    elif progress < .6:
        difficulty = 'Antumbra'
    elif progress < .8:
        difficulty = 'Umbra'
    else:
        difficulty = 'Eclipse'
    return {'difficulty': difficulty, 'progress': 1.0 if final else progress,
            'scene': kind, 'name': name, 'final_stage': final}
