import json, copy, sys

with open('/Users/mac/AinerWorkFlow/AinerZero/reports/V9-T28/r2/proposal.json') as f:
    orig = json.load(f)

# --- Adversarial Test 1: Tamper cumulative_view_cap to 132 ---
print("=== ADVERSARIAL TEST 1: Tamper cumulative_view_cap to 132 ===")
adv1 = copy.deepcopy(orig)
adv1['budget']['view_accounting']['cumulative_view_cap'] = 132

va1 = adv1['budget']['view_accounting']
used = va1['ledger_views_used_before_run']
charge = va1['charge_per_complete_run']
cap = va1['cumulative_view_cap']

is_consistent = (used + charge == cap == 131)
print(f"Adversarial 1 evaluation: used({used}) + charge({charge}) = {used+charge}, cap={cap}")
print(f"Check 2 consistent: {is_consistent}")
if not is_consistent:
    print("SUCCESS: Check 2 successfully caught tampered cumulative_view_cap=132!")
else:
    print("FAILURE: Check 2 failed to catch tamper!")
    sys.exit(1)

# --- Adversarial Test 2: Tamper tolerance in numerical_parity ---
print("\n=== ADVERSARIAL TEST 2: Tamper tolerance translation_norm_rel_max to 0.09 ===")
adv2 = copy.deepcopy(orig)
adv2['numerical_parity']['cpu_float32']['translation_norm_rel_max'] = 0.09

with open('/Users/mac/AinerWorkFlow/AinerZero/reports/V9-T28/r2/pre-E17-2a984531/proposal.json') as f:
    pre = json.load(f)

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

flat_pre = dict(get_leaf_items(pre))
flat_cur = dict(get_leaf_items(adv2))

allowed_prefixes = [
    'amendment',
    'budget.view_accounting',
    'budget.cumulative_wall_seconds_max',
    'budget.wall_accounting',
    'open_items',
]

unallowed = []
for k in set(flat_pre.keys()) | set(flat_cur.keys()):
    v_pre = flat_pre.get(k)
    v_cur = flat_cur.get(k)
    if v_pre != v_cur:
        matched = any(k == p or k.startswith(p + '.') or k.startswith(p + '[') for p in allowed_prefixes)
        if not matched:
            unallowed.append({'key': k, 'pre': v_pre, 'cur': v_cur})

print(f"Unallowed diffs found in Adversarial 2: {len(unallowed)}")
for u in unallowed:
    print(f"Caught unallowed change: {u['key']} (pre={u['pre']}, tampered={u['cur']})")

if len(unallowed) > 0 and any(u['key'] == 'numerical_parity.cpu_float32.translation_norm_rel_max' for u in unallowed):
    print("SUCCESS: Check 1 successfully caught unauthorized tolerance tampering!")
else:
    print("FAILURE: Check 1 failed to catch tolerance tampering!")
    sys.exit(1)

print("\nALL ADVERSARIAL TESTS PASSED (BOTH DEFENSES VERIFIED).")
