import sys, json, os, time
sys.path.insert(0, '/var/www/orion/backend')

# Read API key
try:
    with open('/var/www/orion/backend/.env') as f:
        for line in f:
            if 'OPENROUTER_API_KEY' in line:
                key = line.split('=', 1)[1].strip().strip('"\'')
                os.environ['OPENROUTER_API_KEY'] = key
                break
except:
    pass

from agent_loop import AgentLoop

api_key = os.environ.get('OPENROUTER_API_KEY', '')
print(f'API key: {api_key[:10]}...')

# Use EXACTLY the same model as app.py pro_standard
loop = AgentLoop(
    model='anthropic/claude-sonnet-4.6',  # Same as app.py line 1544
    api_key=api_key,
    api_url='https://openrouter.ai/api/v1/chat/completions',
    ssh_credentials={'host': '2.56.240.170', 'username': 'root', 'password': 'WJljz4QdfW*Jfdf', 'port': 22},
    user_id='test'
)
loop.orion_mode = 'pro_standard'
loop.MAX_ITERATIONS = 5

# Test with DNS task
msg = "Подключись к панели Beget (cp.beget.com), логин asmksm58, пароль 9DVTHeKiYuZD. Измени A-запись для домена asmksm58.beget.tech на 45.67.57.175. Проверь через dig."

print(f'=== RUNNING STREAM (model=claude-sonnet-4.6) ===')
count = 0
start = time.time()
for event in loop.run_stream(msg, [], ''):
    count += 1
    elapsed = round(time.time() - start, 1)
    
    if isinstance(event, dict):
        etype = event.get('type', '?')
        if etype == 'heartbeat':
            continue  # skip heartbeats
        print(f'[{elapsed}s] Event {count}: type={etype}')
        if etype == 'error':
            print(f'  ERROR: {json.dumps(event, ensure_ascii=False)[:300]}')
        elif etype == 'tool_start':
            print(f'  TOOL START: {event.get("tool")} args={str(event.get("args",""))[:150]}')
        elif etype == 'tool_result':
            print(f'  TOOL RESULT: {event.get("tool")} success={event.get("success")} preview={str(event.get("preview",""))[:100]}')
        elif etype == 'content':
            text = event.get('text', '')
            if len(text) > 5:
                print(f'  content: {text[:100]}')
        elif etype in ('task_steps', 'task_complete'):
            print(f'  {json.dumps(event, ensure_ascii=False)[:300]}')
    elif isinstance(event, str):
        try:
            raw = event
            if raw.startswith('data: '):
                raw = raw[6:]
            raw = raw.strip()
            if not raw:
                continue
            data = json.loads(raw)
            etype = data.get('type', '?')
            if etype == 'heartbeat':
                continue
            print(f'[{elapsed}s] Event {count} (str): type={etype}')
            if etype == 'error':
                print(f'  ERROR: {json.dumps(data, ensure_ascii=False)[:300]}')
            elif etype == 'tool_start':
                print(f'  TOOL START: {data.get("tool")} args={str(data.get("args",""))[:150]}')
            elif etype == 'tool_result':
                print(f'  TOOL RESULT: {data.get("tool")} success={data.get("success")} preview={str(data.get("preview",""))[:100]}')
            elif etype == 'content':
                text = data.get('text', '')
                if len(text) > 5:
                    print(f'  content: {text[:100]}')
            elif etype in ('task_steps', 'task_complete'):
                print(f'  {json.dumps(data, ensure_ascii=False)[:300]}')
        except:
            if len(str(event)) > 10:
                print(f'[{elapsed}s] Event {count}: raw={str(event)[:100]}')
    
    if count > 80:
        print('... stopping after 80 events')
        break
    if time.time() - start > 180:
        print('... timeout 180s')
        break

print(f'\nTotal events: {count}, elapsed: {round(time.time()-start,1)}s')
