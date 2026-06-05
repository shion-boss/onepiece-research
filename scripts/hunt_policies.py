# -*- coding: utf-8 -*-
"""複数 bot policy (aggressive / defensive) で 人間経路 × 環境デッキ を叩く エンジンバグ hunt。

⭐ 教訓 (2026-06-05): **seed 変更 < bot 戦術変更**。 同じ policy の bot は同じ行動分布しか
踏まない → 新エンジンバグは「違う打ち方の bot」 で出る。 aggressive (常に効果発動・全候補 pick)
は replace_leave 無限ループ / opp_attack stale payload を、 defensive (攻撃せず長期戦) は終盤/
deck-out edge を踏む。 STUCK (同 pending 80+) = 無限ループ、 INV = 保存則違反、 PY_EXC/ENGINE_ERROR
= crash を検出。

  python scripts/hunt_policies.py
"""
import sys, random
sys.path.insert(0,'scripts'); sys.path.insert(0,'.')
import fuzz_human_play as F
F._setup()
DECKS=F.DECKS
def modal_pick(pl,rng,aggro):
    k=pl.get("kind"); lim=int(pl.get("limit",1) or 1)
    if k in ("mulligan_confirm","mulligan_redrawn"): return [0]
    if k in ("optional_cost_confirm","replace_ko_optional","reveal_top_play_confirm","on_attack_optional","on_opp_attack_optional","end_of_turn_optional","life_taken_choice","view_life_top_choose_position","option_pick"):
        return [1] if aggro else [rng.choice([0,1])]
    if k in ("search_top_n_bottom_reorder","scry_life_reorder","scry_deck_reorder"):
        cs=pl.get("candidates") or pl.get("cards") or []; o=list(range(len(cs))); rng.shuffle(o); return o
    cs=pl.get("candidates") or pl.get("cards") or pl.get("options") or []
    return list(range(min(lim,len(cs)))) if cs else []

def play(a,b,seed,hf,policy):
    s=F._build_session(a,b,seed,hf); rng=random.Random(seed); steps=0; last=None; same=0
    INIT=100
    while not s.state.game_over and steps<3000:
        steps+=1; pk=s.pending_kind; pl=s.pending_payload or {}
        sig=(pk,pl.get("kind"),s.state.turn_number,len(pl.get("available_opp_attack_effects") or []))
        if sig==last:
            same+=1
            if same>80: return ("STUCK",steps,sig)
        else: same=0; last=sig
        try:
            if pk=="action":
                # 保存則 check (安定点)
                t=0
                for p in s.state.players: t+=len(p.deck)+len(p.hand)+len(p.trash)+len(p.life)+len(p.characters)+len(p.stages)
                if t!=INIT: return ("INV",steps,f"maindeck {t}!={INIT}")
                acts=s.legal_actions_for_human()
                if not acts: return ("NO_ACT",steps,None)
                atk=[x for x in acts if x.get("kind") in ("AttackLeader","AttackCharacter")]
                non_end=[x for x in acts if x.get("kind")!="EndPhase"]
                if policy=="aggro":
                    pick=rng.choice(non_end) if non_end else acts[0]
                else:  # defensive: 攻撃しない、 非攻撃アクション優先、 無ければ End
                    nonatk=[x for x in non_end if x not in atk]
                    pick=(rng.choice(nonatk) if nonatk and rng.random()<0.7 else next((x for x in acts if x.get("kind")=="EndPhase"),acts[0]))
                s.apply_human_action(pick["idx"])
            elif pk=="choice":
                s.apply_human_choice(modal_pick(pl,rng,policy=="aggro"))
            elif pk=="defense":
                avail=pl.get("available_opp_attack_effects") or []
                if avail and (policy=="aggro" or rng.random()<0.8):
                    e=avail[0]; s.apply_human_use_opp_attack_effect(e["source_iid"],e["effect_idx"])
                else:
                    blk=pl.get("legal_blocker_iids") or []; cnt=pl.get("legal_counter_card_idxs") or []
                    s.apply_human_defense(blk[0] if blk else None, cnt[:1] if cnt else [])
            else: break
        except Exception as e:
            return ("PY_EXC",steps,f"{type(e).__name__}: {str(e)[:70]}")
    for ln in s.state.log:
        if "engine error" in ln: return ("ENGINE_ERROR",steps,ln.split("engine error:")[-1].strip()[:80])
    return ("OK",steps,None)

pairs=[(d,d) for d in DECKS]
for i,d in enumerate(DECKS):
    for j in (1,2): pairs.append((d,DECKS[(i+j)%len(DECKS)]))
from collections import Counter
bugs=[]; res=Counter(); total=0
for policy in ("aggro","defensive"):
    for a,b in pairs:
        for sd in range(8):
            gs=60000+sd; st,steps,info=play(a,b,gs,sd%2==0,policy)
            res[(policy,st)]+=1; total+=1
            if st!="OK": bugs.append((policy,a,b,gs,st,info))
    print(f"policy={policy} done | total {total} | bugs {len(bugs)}",flush=True)
print(f"\n=== multi-policy hunt {total} 試合 ===")
for k,c in res.most_common(): print(f"  {k}: {c}")
for p,a,b,s,st,info in bugs[:40]: print(f"  ★[{p}/{st}] {a} vs {b} #{s}: {info}")
