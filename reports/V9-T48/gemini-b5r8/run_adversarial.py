import json, copy, sys

with open('/Users/mac/AinerWorkFlow/AinerZero/reports/V9-T28/r2/proposal.json') as f:
    orig = json.load(f)

# --- Adversarial Test A: Tamper charge_per_complete_run to 18 ---
print("=== ADVERSARIAL TEST A: Tamper charge_per_complete_run to 18 ===")
adv_a = copy.deepcopy(orig)
adv_a['budget']['view_accounting']['charge_per_complete_run'] = 18

charge_a = adv_a['budget']['view_accounting']['charge_per_complete_run']
models_a = adv_a['budget']['models']
total_views_calc_a = sum(sum(s['calls'] * len(s['views']) for s in m['stages']) for m in models_a)

passed_a = (charge_a == total_views_calc_a == 50)
print(f"Adversarial A evaluation: charge={charge_a}, total_views_calc={total_views_calc_a}")
print(f"Check 3 verification passed: {passed_a}")
if not passed_a:
    print("SUCCESS: Check 3 successfully caught tampered charge_per_complete_run=18!")
else:
    print("FAILURE: Check 3 failed to catch tamper!")
    sys.exit(1)

# --- Adversarial Test B: Tamper tolerance in numerical_parity ---
print("\n=== ADVERSARIAL TEST B: Tamper tolerance rotation_angle_abs_max to 0.08 ===")
adv_b = copy.deepcopy(orig)
adv_b['numerical_parity']['cpu_float32']['rotation_angle_abs_max'] = 0.08

with open('/Users/mac/AinerWorkFlow/AinerZero/reports/V9-T28/r2/pre-E16-86f5ece6/proposal.json') as f:
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
flat_b = dict(get_leaf_items(adv_b))

allowed_prefixes = [
    'amendment',
    'budget.view_accounting',
    'numerical_parity.retired_stages',
    'open_items',
]

unallowed = []
for k in set(flat_pre.keys()) | set(flat_b.keys()):
    v_pre = flat_pre.get(k)
    v_b = flat_b.get(k)
    if v_pre != v_b:
        matched = any(k == p or k.startswith(p + '.') or k.startswith(p + '[') for p in allowed_prefixes)
        if not matched:
            unallowed.append({'key': k, 'pre': v_pre, 'cur': v_b})

print(f"Unallowed diffs found in Adversarial B: {len(unallowed)}")
for u in unallowed:
    print(f"Caught unallowed change: {u['key']} (pre={u['pre']}, tampered={u['cur']})")

if len(unallowed) > 0 and any(u['key'] == 'numerical_parity.cpu_float32.rotation_angle_abs_max' for u in unallowed):
    print("SUCCESS: Check 1 successfully caught unauthorized tolerance tampering!")
else:
    print("FAILURE: Check 1 failed to catch tolerance tampering!")
    sys.exit(1)

print("\nALL ADVERSARIAL DEFENSES VERIFIED SUCCESSFULLY.")
