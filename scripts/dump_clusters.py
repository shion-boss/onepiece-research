#!/usr/bin/env python3
"""Grind helper: dump top non-deferred clusters (text + overlay) for inline audit.

Usage:
  python scripts/dump_clusters.py [N] [--min-size K] [--start S]
"""
import json
import sys

clusters = json.load(open('db/audit_llm/signature_clusters.json'))
prog = json.load(open('db/audit_llm/full_db_progress.json'))
deferred = set(prog.get('meta', {}).get('deferred_cards', []))
cards = {c['card_id']: c for c in json.load(open('db/cards.json'))}
eff = json.load(open('db/card_effects.json'))

# args
N = 8
min_size = 2
start = 0
args = sys.argv[1:]
i = 0
while i < len(args):
    a = args[i]
    if a == '--min-size':
        min_size = int(args[i + 1]); i += 2
    elif a == '--start':
        start = int(args[i + 1]); i += 2
    else:
        N = int(a); i += 1

cand = [c for c in clusters if c['size'] >= min_size and c['rep'] not in deferred]
print(f'candidates (size>={min_size}, non-deferred): {len(cand)}  showing [{start}:{start+N}]')
print('=' * 72)
for c in cand[start:start + N]:
    rep = c['rep']
    cd = cards.get(rep, {})
    print(f"### REP {rep}  size={c['size']}  members={c['members']}")
    print(f"NAME: {cd.get('name','')} | {cd.get('category','')} | {cd.get('color','')} | cost={cd.get('cost','')} | power={cd.get('power','')} | feat={cd.get('features','')}")
    print('TEXT:', repr(c.get('text', '')))
    if c.get('trigger'):
        print('TRIG:', repr(c['trigger']))
    print('OVERLAY:', json.dumps(eff.get(rep, '<<MISSING>>'), ensure_ascii=False))
    print('-' * 72)
