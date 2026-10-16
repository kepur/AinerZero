"""R2 independent CPU checker, written without importing the R1 validator.

schema = card's presence/format obligations; facts = facts manually checked against
the primary URLs in source_review.json. This checker does not retrieve sources and
does not turn static checks into runtime or capability evidence.
"""
import datetime
import json
import re
import sys
from pathlib import Path
from urllib.parse import urlsplit

IDS = {'h-jepa', 'lewm', 'vjepa2', 'dreamerv3', 'stable-worldmodel',
       'egnn', 'slot-attention', 'thick'}


def https(value):
    parts = urlsplit(value)
    return parts.scheme == 'https' and bool(parts.hostname)


def check(reg, md, mode):
    assert isinstance(reg, dict), 'root object'
    entries = reg['entries']
    assert isinstance(entries, list) and len(entries) == 8, 'exactly eight entries'
    assert {e['id'] for e in entries} == IDS, 'exact IDs without duplicates'
    assert re.fullmatch(r'\d{4}-\d{2}-\d{2}', reg['access_date']), 'access date format'
    try:
        date = datetime.date.fromisoformat(reg['access_date'])
    except ValueError:
        date = None
    assert date is not None, 'access date must be a real calendar date'
    assert date <= datetime.date(2026, 10, 16), 'access date cannot be future'
    rows = {}
    for line in md.splitlines():
        if line.startswith('| '):
            cells = [s.strip() for s in line.strip('|').split('|')]
            if cells[0] in IDS:
                assert cells[0] not in rows, 'duplicate markdown row'
                rows[cells[0]] = cells
    assert set(rows) == IDS, 'all eight markdown rows'
    for e in entries:
        key = e['id']
        assert isinstance(e['name'], str) and e['name'].strip(), key + ': name'
        assert https(e['paper']['url']), key + ': valid paper URL'
        assert e['paper']['url'] in md, key + ': paper URL in markdown'
        assert isinstance(e['paper']['authors'], list) and all(e['paper']['authors']), key + ': authors'
        assert re.search(r'20\d\d', e['paper']['date']), key + ': paper version/date'
        assert https(e['repo']['url']) or e['repo']['url'].startswith('未找到'), key + ': repository URL/explicit unknown'
        assert e['license']['license'].strip() and e['license']['source'].strip(), key + ': license/source'
        for field in ['borrowable_mechanisms', 'non_inferables']:
            assert isinstance(e[field], list) and e[field] and all(isinstance(s, str) and s.strip() for s in e[field]), key + ': ' + field
        mlx = e['mlx_feasibility']
        assert mlx['rating'].strip() and mlx['notes'].strip(), key + ': MLX assessment'
        assert isinstance(mlx['deps'], list) and mlx['deps'] and all(mlx['deps']), key + ': dependencies'
        assert e['status'] in ['verified', 'verified-paper-only'], key + ': status'
        for token in re.findall(r'MIT|Apache-2\.0', e['license']['license']):
            assert token in rows[key][4], key + ': MD/JSON license disagreement'
    if mode != 'schema':
        emap = {e['id']: e for e in entries}
        if mode in ['facts', 'date']:
            assert emap['stable-worldmodel']['paper']['date'].startswith('2026-05-20'), 'stable-worldmodel v1 submission = 2026-05-20, not 2026-05-26'
        if mode in ['facts', 'thick_repo']:
            assert emap['thick']['repo']['url'] == 'https://github.com/CognitiveModeling/THICK', 'THICK author-linked TF2 repository exists'
        if mode in ['facts', 'thick_license']:
            assert emap['thick']['license']['license'] == 'MIT', 'THICK TF2 root LICENSE is MIT; do not inherit this to thix'
    print('PASS ' + mode)


if __name__ == '__main__':
    mode, jp, mp = sys.argv[1:]
    check(json.loads(Path(jp).read_text()), Path(mp).read_text(), mode)
