"""Collect verbatim numbered citations; never imports project modules."""
import hashlib
import json
from pathlib import Path

here=Path(__file__).resolve().parent
root=here.parents[2]
spans={
 'reports/V9-S6-DESIGN/DESIGN-r2.md':[(253,267),(277,295),(319,343)],
 'reports/V9-S6-PHASE1/run_s6p1.py':[(43,50),(121,130),(244,254),(271,313)],
 'reports/V9-S6-PHASE1/verify_s6p1.py':[(20,22),(51,72),(76,98)],
 'reports/V9-S6-PHASE1/make_prereg.py':[(50,60)],
 'src/ainerzero/v9/experiments/s6/cells.py':[(40,42),(330,360),(363,390),(415,429)],
 'src/ainerzero/v9/experiments/s6/analysis.py':[(45,69),(268,297)],
 'src/ainerzero/v9/experiments/s4/world.py':[(189,214)],
}
lines=[]
for rel,ranges in spans.items():
    p=root/rel
    text=p.read_text().splitlines()
    lines += [f'FILE {rel}',f'SHA256 {hashlib.sha256(p.read_bytes()).hexdigest()}']
    for a,b in ranges:
        lines += [f'{i}: {text[i-1]}' for i in range(a,min(b,len(text))+1)]
    lines += ['']
with (here/'citations.txt').open('x') as f:
    f.write('\n'.join(lines))
