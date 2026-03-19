import sys, json, os
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

loop = AgentLoop(
    model='anthropic/claude-sonnet-4-20250514',
    api_key=api_key,
    api_url='https://openrouter.ai/api/v1/chat/completions',
    ssh_credentials={'host': '2.56.240.170', 'username': 'root', 'password': 'WJljz4QdfW*Jfdf', 'port': 22},
    user_id='test'
)
loop.orion_mode = 'pro_standard'
loop.MAX_ITERATIONS = 3

print('=== RUNNING STREAM ===')
count = 0
for event in loop.run_stream('Выполни команду: echo DNS_TEST_OK', [], ''):
    count += 1
    if isinstance(event, dict):
        etype = event.get('type', '?')
        print(f'Event {count}: type={etype} keys={list(event.keys())}')
        if etype == 'error':
            print(f'  ERROR: {event}')
        elif etype == 'tool_result':
            print(f'  tool={event.get("tool")} success={event.get("success")} preview={str(event.get("preview",""))[:100]}')
        elif etype == 'content':
            print(f'  text={str(event.get("text",""))[:100]}')
    elif isinstance(event, str):
        try:
            data = json.loads(event.replace('data: ', '').strip())
            etype = data.get('type', '?')
            print(f'Event {count}: type={etype}')
            if etype == 'error':
                print(f'  ERROR: {data}')
            elif etype == 'tool_result':
                print(f'  tool={data.get("tool")} success={data.get("success")}')
        except:
            print(f'Event {count}: str={str(event)[:150]}')
    else:
        print(f'Event {count}: unknown type={type(event)} val={str(event)[:100]}')
    
    if count > 50:
        print('... stopping after 50 events')
        break

print(f'\nTotal events: {count}')
