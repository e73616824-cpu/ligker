import random
import time
from leagues import get_league_by_id
from data_manager import (
    get_all_guild_ids, get_guild_data,
    get_league_state, save_league_state, add_match_to_log
)

def get_team_strength(team):
    players = team.get('players', [])
    if not players:
        return 70.0
    return sum(p.get('overall', 70) for p in players) / len(players)

def simulate_goals(strength, opp_strength):
    diff = strength - opp_strength
    base = 1.5 + (diff / 30)
    max_goals = max(0, round(base + random.random() * 2.5))
    return max(0, min(max_goals, 7))

def pick_scorer(players):
    weights = {'ST': 40, 'LW': 25, 'RW': 25, 'CAM': 20, 'CM': 10, 'LB': 3, 'RB': 3, 'CB': 2, 'GK': 0}
    pool = []
    for p in players:
        w = weights.get(p.get('position', ''), 5)
        pool.extend([p['name']] * w)
    return random.choice(pool) if pool else random.choice(players)['name']

def generate_events(home_team, away_team, home_goals, away_goals):
    events = []
    used_mins = set()
    def get_minute():
        while True:
            m = random.randint(1, 90)
            if m not in used_mins:
                used_mins.add(m)
                return m

    for _ in range(home_goals):
        events.append({'type': 'goal', 'team': home_team['shortName'], 'player': pick_scorer(home_team['players']), 'minute': get_minute()})
    for _ in range(away_goals):
        events.append({'type': 'goal', 'team': away_team['shortName'], 'player': pick_scorer(away_team['players']), 'minute': get_minute()})
    for _ in range(random.randint(1, 4)):
        team = random.choice([home_team, away_team])
        player = random.choice(team['players'])
        events.append({'type': 'yellow', 'team': team['shortName'], 'player': player['name'], 'minute': get_minute()})
    if random.random() < 0.1:
        team = random.choice([home_team, away_team])
        player = random.choice(team['players'])
        events.append({'type': 'red', 'team': team['shortName'], 'player': player['name'], 'minute': get_minute()})
    return sorted(events, key=lambda e: e['minute'])

def build_match_message(home_team, away_team, result):
    lines = [
        "⚽ <b>MAÇA BAŞLANIYOR!</b>",
        f"🏟️ <i>{home_team.get('stadium', 'Ev Sahası')}</i>\n",
    ]
    for ev in result['events']:
        m = str(ev['minute']).rjust(2)
        if ev['type'] == 'goal':
            emoji = '🟢' if ev['team'] == home_team['shortName'] else '🔴'
            lines.append(f"<code>{m}'</code> {emoji} <b>GOL! {ev['player']}</b> ({ev['team']})")
        elif ev['type'] == 'yellow':
            lines.append(f"<code>{m}'</code> 🟡 Sarı kart: {ev['player']} ({ev['team']})")
        elif ev['type'] == 'red':
            lines.append(f"<code>{m}'</code> 🔴 Kırmızı kart: {ev['player']} ({ev['team']})")
    hg, ag = result['home_goals'], result['away_goals']
    lines.append("\n⏱️ <b>MAÇIN SONU!</b>")
    lines.append(f"{home_team.get('emoji', '')} <b>{home_team['shortName']} {hg} – {ag} {away_team['shortName']}</b> {away_team.get('emoji', '')}")
    if hg > ag:
        lines.append(f"🏆 <b>{home_team['shortName']}</b> kazandı!")
    elif ag > hg:
        lines.append(f"🏆 <b>{away_team['shortName']}</b> kazandı!")
    else:
        lines.append("🤝 <b>Beraberlik!</b>")
    return '\n'.join(lines)

def simulate_match(home_team, away_team):
    home_str = get_team_strength(home_team) + 3  # ev avantajı
    away_str = get_team_strength(away_team)
    home_goals = simulate_goals(home_str, away_str)
    away_goals = simulate_goals(away_str, home_str)
    events = generate_events(home_team, away_team, home_goals, away_goals)
    return {
        'home_team': home_team['shortName'],
        'away_team': away_team['shortName'],
        'home_goals': home_goals,
        'away_goals': away_goals,
        'events': events,
        'timestamp': int(time.time())
    }

def update_standings(standings, home_id, away_id, hg, ag):
    h = standings.get(home_id)
    a = standings.get(away_id)
    if not h or not a:
        return
    h['played'] += 1; a['played'] += 1
    h['goals_for'] += hg; h['goals_against'] += ag
    a['goals_for'] += ag; a['goals_against'] += hg
    h['goal_diff'] = h['goals_for'] - h['goals_against']
    a['goal_diff'] = a['goals_for'] - a['goals_against']
    if hg > ag:
        h['won'] += 1; h['points'] += 3; a['lost'] += 1
    elif ag > hg:
        a['won'] += 1; a['points'] += 3; h['lost'] += 1
    else:
        h['drawn'] += 1; a['drawn'] += 1; h['points'] += 1; a['points'] += 1

def build_trophy_message(state):
    """Lig sonu kupa mesajı."""
    sorted_s = sorted(state['standings'].values(), key=lambda t: (-t['points'], -t['goal_diff']))
    champion = sorted_s[0]
    medals = ['🥇', '🥈', '🥉']
    podium = '\n'.join(
        f"{medals[i]} <b>{t['team_name']}</b> — {t['points']} puan ({t['won']}G {t['drawn']}B {t['lost']}M)"
        for i, t in enumerate(sorted_s[:3])
    )
    # En çok gol atan takım
    top_scorer_team = max(sorted_s, key=lambda t: t['goals_for'])

    msg = (
        f"🏆 <b>{state['league_name']} — LİG TAMAMLANDI!</b>\n\n"
        f"🎉🎊 TEBRİKLER! 🎊🎉\n\n"
        f"👑 <b>ŞAMPİYON: {champion['team_name']}</b> 👑\n"
        f"⭐ {champion['points']} puan | {champion['won']}G {champion['drawn']}B {champion['lost']}M\n"
        f"⚽ {champion['goals_for']} gol attı\n\n"
        f"🏅 <b>Podyum:</b>\n{podium}\n\n"
        f"📊 <b>İstatistikler:</b>\n"
        f"🔥 En çok gol: <b>{top_scorer_team['team_name']}</b> ({top_scorer_team['goals_for']} gol)\n"
        f"📅 Toplam Hafta: {state['total_rounds']}\n\n"
        f"🏆 Kupa <b>{champion['team_name']}</b>'e teslim edildi!\n"
        f"Tebrikler şampiyona! 🎉"
    )
    return msg

def init_league(guild_id, league_id):
    """Geriye dönük uyumluluk için eski init_league fonksiyonu."""
    league_data = get_league_by_id(league_id)
    if not league_data:
        raise ValueError(f"Lig bulunamadı: {league_id}")
    teams = league_data['teams']

    # Round-robin: her takım diğerleriyle ev+deplasman 2 maç
    from bot import generate_fixtures
    fixtures = generate_fixtures(teams)

    standings = {
        t['id']: {
            'team_id': t['id'], 'team_name': t.get('shortName', t['name']),
            'played': 0, 'won': 0, 'drawn': 0, 'lost': 0,
            'goals_for': 0, 'goals_against': 0, 'goal_diff': 0, 'points': 0
        }
        for t in teams
    }
    state = {
        'league_id': league_id,
        'league_name': league_data['name'],
        'status': 'active',
        'current_round': 0,
        'total_rounds': len(fixtures),
        'fixtures': fixtures,
        'standings': standings,
        'registered_teams': [t['id'] for t in teams],
        'participants': {},
        'started_at': int(time.time()),
        'last_match_day': None
    }
    save_league_state(guild_id, league_id, state)
    return state

async def simulate_match_day(app):
    import asyncio
    for guild_id in get_all_guild_ids():
        try:
            guild_data = get_guild_data(guild_id)
            chat_id = guild_data.get('announce_channel') or guild_id

            for league_id, state in guild_data.get('leagues', {}).items():
                # Sadece aktif liglerde maç oynanır
                if state.get('status') != 'active':
                    continue

                next_round = state['current_round'] + 1
                league_data = get_league_by_id(league_id)
                if not league_data:
                    continue

                # Lig bitti mi?
                if next_round > state['total_rounds']:
                    state['status'] = 'finished'
                    save_league_state(guild_id, league_id, state)
                    trophy_msg = build_trophy_message(state)
                    await app.bot.send_message(chat_id=chat_id, text=trophy_msg, parse_mode='HTML')
                    continue

                # Hafta başlangıç mesajı
                round_data = state['fixtures'][next_round - 1]
                await app.bot.send_message(
                    chat_id=chat_id,
                    text=f"{league_data.get('emoji', '')} <b>{state['league_name']} — Hafta {next_round}/{state['total_rounds']}</b>\n\nMaçlar başlıyor... ⚽",
                    parse_mode='HTML'
                )

                # Takım haritası
                all_teams = {t['id']: t for t in league_data['teams']}

                for match in round_data['matches']:
                    home_team = all_teams.get(match['home'])
                    away_team = all_teams.get(match['away'])
                    if not home_team or not away_team:
                        continue

                    result = simulate_match(home_team, away_team)
                    update_standings(state['standings'], match['home'], match['away'],
                                     result['home_goals'], result['away_goals'])
                    add_match_to_log(guild_id, {**result, 'league': state['league_name']})
                    await app.bot.send_message(
                        chat_id=chat_id,
                        text=build_match_message(home_team, away_team, result),
                        parse_mode='HTML'
                    )
                    await asyncio.sleep(1.5)

                state['current_round'] = next_round
                state['last_match_day'] = int(time.time())
                save_league_state(guild_id, league_id, state)

                # Hafta sonu özet puan durumu (ilk 5)
                sorted_s = sorted(state['standings'].values(),
                                  key=lambda t: (-t['points'], -t['goal_diff']))[:5]
                medals = ['🥇', '🥈', '🥉', '4️⃣', '5️⃣']
                rows = '\n'.join(
                    f"{medals[i]} <b>{t['team_name']}</b> — {t['points']} puan ({t['won']}G {t['drawn']}B {t['lost']}M)"
                    for i, t in enumerate(sorted_s)
                )
                remaining = state['total_rounds'] - next_round
                await app.bot.send_message(
                    chat_id=chat_id,
                    text=f"📊 <b>{state['league_name']} — Hafta {next_round} Sonrası</b>\n\n{rows}\n\n📅 Kalan hafta: {remaining}",
                    parse_mode='HTML'
                )

                # Lig bu tur bittiyse kupa ver
                if next_round >= state['total_rounds']:
                    await asyncio.sleep(2)
                    state['status'] = 'finished'
                    save_league_state(guild_id, league_id, state)
                    trophy_msg = build_trophy_message(state)
                    await app.bot.send_message(chat_id=chat_id, text=trophy_msg, parse_mode='HTML')

        except Exception as e:
            print(f"[HATA] Guild {guild_id}: {e}")
            import traceback
            traceback.print_exc()
