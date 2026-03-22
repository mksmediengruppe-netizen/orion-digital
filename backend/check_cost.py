import sqlite3

conn = sqlite3.connect('data/database.sqlite')
c = conn.cursor()

c.execute('SELECT count(*) FROM chats WHERE total_cost > 0')
print(f'Chats with cost > 0: {c.fetchone()[0]}')

c.execute('SELECT count(*) FROM chats WHERE total_cost = 0 OR total_cost IS NULL')
print(f'Chats with cost = 0: {c.fetchone()[0]}')

c.execute('SELECT sum(total_cost) FROM chats')
total = c.fetchone()[0]
print(f'Total cost in DB: ${total}')

c.execute('SELECT id, title, total_cost FROM chats WHERE total_cost > 0 ORDER BY total_cost DESC LIMIT 5')
print('\nTop 5 chats by cost:')
for row in c.fetchall():
    print(f'  ${row[2]:.4f} | {row[1][:60]}')

# Check user total_spent
c.execute('SELECT name, total_spent FROM users')
print('\nUsers:')
for row in c.fetchall():
    print(f'  {row[0]}: ${row[1]}')

# Check cost_log.json
import json
try:
    cl = json.load(open('data/cost_log.json'))
    total_log = sum(e.get('cost_usd', 0) for e in cl)
    print(f'\ncost_log.json: {len(cl)} entries, total: ${total_log:.4f}')
    # Pro mode entries
    pro_entries = [e for e in cl if 'pro' in str(e.get('mode', '')).lower()]
    print(f'Pro mode entries: {len(pro_entries)}')
    for e in pro_entries[-3:]:
        print(f'  ${e.get("cost_usd", 0):.4f} | {e.get("mode")} | {e.get("model_id")} | tokens: {e.get("tokens_in", 0)}+{e.get("tokens_out", 0)}')
except Exception as ex:
    print(f'cost_log.json error: {ex}')
