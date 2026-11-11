"""P215（复核者 b）：把我在锁下复跑的前 N 个世界与前一持有者的 records-heuristics.json 逐字段比对。纯 CPU。
用法：python -I -B compare_rerun.py <前一持有者的 records> <我的复跑 records>"""
import json, sys
a, b = json.load(open(sys.argv[1]))["records"], json.load(open(sys.argv[2]))["records"]
n = len(b); same = [json.dumps(a[i], sort_keys=True) == json.dumps(b[i], sort_keys=True) for i in range(n)]
cells = sum(len(r["cells"]) for r in b)
print(f"rerun worlds {n}, cells {cells}; identical worlds {sum(same)}/{n}; worlds compared: {[(r['kind'], r['world']) for r in b]}")
