"""Own-agent heartbeat/inbox watcher. No worker execution or next-card claim."""
import datetime
import json
from pathlib import Path
import subprocess
import time

HERE=Path(__file__).resolve().parent
RELAY='/Users/mac/AinerWorkFlow/AinerRelay/bin/relay'
AGENT='codex-s6probe-rv-1115'
TASK='ainerzero.V9.P260'
seen=set()
due=0
while True:
    if (HERE/'STOP_HEARTBEAT').exists():
        break
    commands=[]
    if time.monotonic()>=due:
        commands.append(['heartbeat',TASK,'--agent',AGENT,'--msg','P260独立CPU工具就绪/复核进行；仅指定目录写入，不导入MLX；等待一级完整eval可读通知后比较'])
        due=time.monotonic()+175
    commands.append(['inbox','--agent',AGENT,'--task',TASK,'--json'])
    for cmd in commands:
        p=subprocess.run(['python3',RELAY,*cmd],capture_output=True,text=True,timeout=25)
        now=datetime.datetime.now(datetime.timezone.utc).isoformat()
        item=dict(time=now,command=cmd,returncode=p.returncode,stdout=p.stdout,stderr=p.stderr)
        with (HERE/'heartbeat-inbox.jsonl').open('a') as f:
            f.write(json.dumps(item,ensure_ascii=False)+'\n')
        if cmd[0]=='heartbeat':
            print(now,p.stdout.strip(),flush=True)
        elif p.returncode==0:
            for msg in json.loads(p.stdout).get('messages',[]):
                if msg['id'] not in seen:
                    seen.add(msg['id'])
                    print(json.dumps(msg,ensure_ascii=False),flush=True)
    time.sleep(20)
