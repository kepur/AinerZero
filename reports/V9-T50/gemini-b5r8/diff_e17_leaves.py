import json

def get_leaf_items(d, prefix=''):
    items = []
    if isinstance(d, dict):
        for k, v in d.items():
            new_prefix = f'{prefix}.{k}' if prefix else k
            items.extend(get_leaf_items(v, new_prefix))
    elif isinstance(d, list):
        for i, v in enumerate(d):
            new_prefix = f'{prefix}[{i}]'
            items.extend(get_leaf_items(v, new_prefix))
    else:
        items.append((prefix, d))
    return items

pre_path = '/Users/mac/AinerWorkFlow/AinerZero/reports/V9-T28/r2/pre-E17-2a984531/proposal.json'
cur_path = '/Users/mac/AinerWorkFlow/AinerZero/reports/V9-T28/r2/proposal.json'

with open(pre_path) as f:
    pre = json.load(f)
with open(cur_path) as f:
    cur = json.load(f)

flat_pre = dict(get_leaf_items(pre))
flat_cur = dict(get_leaf_items(cur))

all_keys = sorted(set(flat_pre.keys()) | set(flat_cur.keys()))

allowed_prefixes = [
    'amendment',
    'budget.view_accounting',
    'budget.cumulative_wall_seconds_max',
    'budget.wall_accounting',
    'open_items',
]

diffs = []
unallowed_diffs = []

for k in all_keys:
    in_pre = k in flat_pre
    in_cur = k in flat_cur
    v_pre = flat_pre.get(k)
    v_cur = flat_cur.get(k)
    if not in_pre:
        diffs.append({'key': k, 'type': 'added', 'cur': v_cur})
    elif not in_cur:
        diffs.append({'key': k, 'type': 'removed', 'pre': v_pre})
    elif v_pre != v_cur:
        diffs.append({'key': k, 'type': 'changed', 'pre': v_pre, 'cur': v_cur})
    else:
        continue
    
    matched = any(k == p or k.startswith(p + '.') or k.startswith(p + '[') for p in allowed_prefixes)
    if not matched:
        unallowed_diffs.append({'key': k, 'pre': v_pre, 'cur': v_cur})

print(f"Total leaf diffs: {len(diffs)}")
print(f"Unallowed leaf diffs: {len(unallowed_diffs)}")

out_data = {
    'total_diffs': len(diffs),
    'unallowed_diffs_count': len(unallowed_diffs),
    'unallowed_diffs': unallowed_diffs,
    'diffs': diffs
}

with open('/Users/mac/AinerWorkFlow/AinerZero/reports/V9-T50/gemini-b5r8/logs/leaf_diff.json', 'w') as f:
    json.dump(out_data, f, indent=2, ensure_ascii=False)

for d in diffs:
    print(f"{d['key']}: {d.get('type')}")
