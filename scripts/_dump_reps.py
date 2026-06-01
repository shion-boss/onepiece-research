"""Quick dump: card text(+trigger) vs overlay for audit grind. Usage: python scripts/_dump_reps.py OP04-058 OP02-002 ..."""
import json, sys

cards = {c['card_id']: c for c in json.load(open('db/cards.json'))}
eff = json.load(open('db/card_effects.json'))

for r in sys.argv[1:]:
    c = cards.get(r, {})
    print('=' * 72)
    print(f"{r}  [{c.get('name','?')}]  {c.get('category','?')}  cost={c.get('cost','?')} power={c.get('power','?')} color={c.get('color','?')}")
    print('feature:', c.get('features'))
    print('--- TEXT ---')
    print(c.get('text', '(none)'))
    if c.get('trigger'):
        print('--- TRIGGER ---')
        print(c.get('trigger'))
    print('--- OVERLAY ---')
    print(json.dumps(eff.get(r, '(no overlay)'), ensure_ascii=False, indent=1))
