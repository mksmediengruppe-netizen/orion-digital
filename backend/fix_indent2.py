with open('agent_loop.py', 'r') as f:
    content = f.read()

# Проблема: heartbeat вставился, но iteration += 1 потерял отступ
# Строка 4391: '            iteration += 1\n' (12 пробелов вместо 16)
# Нужно исправить: убрать heartbeat из этого места и вставить правильно

# Паттерн: yield heartbeat, потом iteration += 1 с неправильным отступом (12 пробелов)
bad_pattern = '                yield {"type": "heartbeat", "message": "agent_thinking"}\n            iteration += 1\n'
good_pattern = '                iteration += 1\n                yield {"type": "heartbeat", "message": "agent_thinking"}\n'

if bad_pattern in content:
    content = content.replace(bad_pattern, good_pattern, 1)
    with open('agent_loop.py', 'w') as f:
        f.write(content)
    print('Fixed indentation for heartbeat in pipeline loop')
else:
    print('Pattern not found, checking...')
    # Показать что есть
    idx = content.find('iteration += 1')
    print(repr(content[idx-100:idx+50]))
