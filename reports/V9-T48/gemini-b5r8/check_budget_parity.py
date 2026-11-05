import json

with open('/Users/mac/AinerWorkFlow/AinerZero/reports/V9-T28/r2/proposal.json') as f:
    p = json.load(f)

budget = p.get('budget', {})
va = budget.get('view_accounting', {})
charge = va.get('charge_per_complete_run')

models = budget.get('models', [])
model_views = []
for m in models:
    v_name = m.get('variant')
    st = m.get('stages', [])
    calc_v = 0
    stage_breakdown = {}
    for s in st:
        st_name = s.get('stage')
        calls = s.get('calls')
        v_list = s.get('views', [])
        v_count = calls * len(v_list)
        calc_v += v_count
        stage_breakdown[st_name] = f"{calls} calls * {len(v_list)} views = {v_count}"
    model_views.append((v_name, m.get('forward_views'), calc_v, stage_breakdown))

total_views_calc = sum(x[2] for x in model_views)

c_wall = budget.get('cumulative_wall_seconds_max')
status = p.get('status')
exec_perm = p.get('execution_permitted')

print(f"charge_per_complete_run: {charge}")
print(f"total_planned_forward_views: {budget.get('total_planned_forward_views')}")
for v_name, decl_v, calc_v, breakdown in model_views:
    print(f"Model {v_name}: declared={decl_v}, calculated={calc_v}, breakdown={breakdown}")
print(f"Total calculated views across models: {total_views_calc}")
print(f"charge_per_complete_run == total_views_calc (50 == 50): {charge == total_views_calc == 50}")
print(f"cumulative_wall_seconds_max is None: {c_wall is None}")
print(f"status == 'proposal_unapproved': {status == 'proposal_unapproved'}")
print(f"execution_permitted == False: {exec_perm is False}")

assert charge == 50
assert total_views_calc == 50
assert c_wall is None
assert status == 'proposal_unapproved'
assert exec_perm is False
print("Verification 3 Passed: 100% compliant!")
