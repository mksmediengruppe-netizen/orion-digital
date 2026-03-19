with open('agent_loop.py', 'r') as f:
    lines = f.readlines()

# Найдем строки с проблемой (heartbeat + iteration += 1 не в цикле)
for i, line in enumerate(lines):
    # Ищем паттерн: yield heartbeat, потом iteration += 1 с неправильным отступом
    if 'yield {"type": "heartbeat"' in line or "yield {'type': 'heartbeat'" in line:
        print(f'Line {i+1}: {repr(line)}')
        if i+1 < len(lines):
            print(f'Line {i+2}: {repr(lines[i+1])}')
        if i+2 < len(lines):
            print(f'Line {i+3}: {repr(lines[i+2])}')
        print('---')
