import asyncio
import time
import random
from datetime import datetime, timezone
from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import Application, CommandHandler, CallbackQueryHandler, ContextTypes
from leagues import get_leagues, get_league_by_id, get_team_by_id, search_team, search_player
from data_manager import (
    get_user_team, set_user_team, get_league_state, save_league_state,
    get_training_data, save_training_data, get_match_log,
    set_announce_channel, get_announce_channel, get_guild_data, save_guild_data
)
from match_engine import simulate_match_day
import re

TOKEN = "8618492952:AAFk5EPHoYYl9ZMJLYTDiEjrjlMyuhPkAl8"

TRAINING_TYPES = {
    'kondisyon':     {'name': 'Kondisyon Antrenmanı', 'emoji': '🏃', 'xp': 20, 'desc': 'Dayanıklılık artırır'},
    'teknik':        {'name': 'Teknik Antrenman',     'emoji': '⚽', 'xp': 25, 'desc': 'Pas ve top kontrolü'},
    'taktik':        {'name': 'Taktik Antrenman',     'emoji': '📋', 'xp': 30, 'desc': 'Savunma/hücum organizasyonu'},
    'gucantrenman':  {'name': 'Güç Antrenmanı',       'emoji': '💪', 'xp': 20, 'desc': 'Fiziksel güç ve hız'},
    'atismapraktik': {'name': 'Atış Pratiği',         'emoji': '🎯', 'xp': 28, 'desc': 'Şut isabeti'},
}
COOLDOWN_HOURS = 6

# Serbest oyuncu havuzu (oyunculara takımı olmayan stat verileri)
FREE_AGENT_POOL = [
    {'id': 'fa_001', 'name': 'Carlos Ruiz', 'position': 'ST', 'overall': 72, 'age': 28, 'nationality': 'Meksika', 'wage': 15000},
    {'id': 'fa_002', 'name': 'Ahmed Hassan', 'position': 'CM', 'overall': 69, 'age': 24, 'nationality': 'Mısır', 'wage': 12000},
    {'id': 'fa_003', 'name': 'Tomás Novak', 'position': 'CB', 'overall': 74, 'age': 31, 'nationality': 'Çek Cumhuriyeti', 'wage': 18000},
    {'id': 'fa_004', 'name': 'Kwame Asante', 'position': 'LW', 'overall': 76, 'age': 22, 'nationality': 'Gana', 'wage': 22000},
    {'id': 'fa_005', 'name': 'Dmitri Volkov', 'position': 'GK', 'overall': 71, 'age': 27, 'nationality': 'Rusya', 'wage': 14000},
    {'id': 'fa_006', 'name': 'Luca Ferrari', 'position': 'CAM', 'overall': 77, 'age': 25, 'nationality': 'İtalya', 'wage': 25000},
    {'id': 'fa_007', 'name': 'Park Jinho', 'position': 'RB', 'overall': 70, 'age': 26, 'nationality': 'G.Kore', 'wage': 13000},
    {'id': 'fa_008', 'name': 'Stefan Müller', 'position': 'CM', 'overall': 73, 'age': 29, 'nationality': 'Avusturya', 'wage': 16000},
    {'id': 'fa_009', 'name': 'Emre Demir', 'position': 'ST', 'overall': 68, 'age': 21, 'nationality': 'Türkiye', 'wage': 10000},
    {'id': 'fa_010', 'name': 'Cristian Vega', 'position': 'LB', 'overall': 71, 'age': 30, 'nationality': 'Şili', 'wage': 14000},
    {'id': 'fa_011', 'name': 'Adama Diallo', 'position': 'RW', 'overall': 75, 'age': 23, 'nationality': 'Senegal', 'wage': 20000},
    {'id': 'fa_012', 'name': 'Nikola Petrov', 'position': 'CB', 'overall': 72, 'age': 32, 'nationality': 'Sırbistan', 'wage': 13000},
    {'id': 'fa_013', 'name': 'Marco Santos', 'position': 'CAM', 'overall': 78, 'age': 26, 'nationality': 'Brezilya', 'wage': 28000},
    {'id': 'fa_014', 'name': 'Jan Kowalski', 'position': 'GK', 'overall': 73, 'age': 28, 'nationality': 'Polonya', 'wage': 15000},
    {'id': 'fa_015', 'name': 'Ali Çelik', 'position': 'ST', 'overall': 70, 'age': 24, 'nationality': 'Türkiye', 'wage': 11000},
]

def gid(update): return str(update.effective_chat.id)
def uid(update): return str(update.effective_user.id)

async def is_admin(update, context):
    try:
        member = await context.bot.get_chat_member(update.effective_chat.id, update.effective_user.id)
        return member.status in ('creator', 'administrator')
    except:
        return True

def estimate_value(player):
    age = player.get('age', 27)
    age_factor = 1.5 if age < 23 else 1.2 if age < 27 else 1.0 if age < 30 else 0.7 if age < 33 else 0.4
    pos_mult = {'ST':1.3,'CAM':1.2,'LW':1.2,'RW':1.2,'CM':1.0,'CB':0.9,'RB':0.9,'LB':0.9,'GK':0.8}.get(player.get('position',''),1)
    raw = ((player.get('overall',70) - 60) / 30) ** 2 * 150 * age_factor * pos_mult
    return round(max(raw, 1) * 10) / 10

# ─── Transfer yardımcıları ────────────────────────────────────────────────────
def get_user_squad(guild_id: str, user_id: str) -> dict:
    data = get_guild_data(guild_id)
    squads = data.setdefault('user_squads', {})
    if user_id not in squads:
        team_id = data.get('user_teams', {}).get(user_id)
        budget = 50_000_000
        if team_id:
            td = get_team_by_id(team_id)
            if td:
                budget = td['team'].get('budget', 50_000_000)
        squads[user_id] = {'budget': budget, 'players': [], 'sold': []}
        save_guild_data(guild_id, data)
    return squads[user_id]

def save_user_squad(guild_id: str, user_id: str, squad: dict):
    data = get_guild_data(guild_id)
    data.setdefault('user_squads', {})[user_id] = squad
    save_guild_data(guild_id, data)

# ─── Lig yardımcıları ─────────────────────────────────────────────────────────
def generate_fixtures(teams):
    """Her takım diğer tüm takımlarla 2 maç yapar (ev + deplasman)."""
    n = len(teams)
    fixtures = []
    # Round-robin algoritması
    team_list = list(teams)
    if n % 2 == 1:
        team_list.append({'id': '__bye__', 'shortName': 'BYE'})  # tek sayı için
    n2 = len(team_list)
    rounds_per_leg = n2 - 1
    # İlk devre
    for rnd in range(rounds_per_leg):
        matches = []
        for i in range(n2 // 2):
            h = team_list[i]
            a = team_list[n2 - 1 - i]
            if rnd % 2 == 0:
                home, away = h, a
            else:
                home, away = a, h
            if h['id'] != '__bye__' and a['id'] != '__bye__':
                matches.append({'home': home['id'], 'away': away['id']})
        # Rotation (sabit ilk eleman, diğerleri döner)
        team_list = [team_list[0]] + [team_list[-1]] + team_list[1:-1]
        fixtures.append({'round': rnd + 1, 'matches': matches})
    # İkinci devre (ev-deplasman yer değiştirir)
    team_list = list(teams)
    if n % 2 == 1:
        team_list.append({'id': '__bye__', 'shortName': 'BYE'})
    for rnd in range(rounds_per_leg):
        matches = []
        for i in range(n2 // 2):
            h = team_list[i]
            a = team_list[n2 - 1 - i]
            if rnd % 2 == 0:
                home, away = a, h  # ters
            else:
                home, away = h, a
            if h['id'] != '__bye__' and a['id'] != '__bye__':
                matches.append({'home': home['id'], 'away': away['id']})
        team_list = [team_list[0]] + [team_list[-1]] + team_list[1:-1]
        fixtures.append({'round': rounds_per_leg + rnd + 1, 'matches': matches})
    return fixtures

def init_league_with_teams(guild_id, league_id, team_ids=None):
    """Lig başlatır. team_ids verilmezse ligdeki tüm takımlar kullanılır."""
    from data_manager import save_league_state
    league_data = get_league_by_id(league_id)
    if not league_data:
        raise ValueError(f"Lig bulunamadı: {league_id}")

    if team_ids:
        teams = [t for t in league_data['teams'] if t['id'] in team_ids]
    else:
        teams = league_data['teams']

    if len(teams) < 2:
        raise ValueError("En az 2 takım gerekli!")

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
        'status': 'waiting',  # waiting = katılım bekleniyor
        'current_round': 0,
        'total_rounds': len(fixtures),
        'fixtures': fixtures,
        'standings': standings,
        'registered_teams': [t['id'] for t in teams],
        'started_at': int(time.time()),
        'last_match_day': None
    }
    save_league_state(guild_id, league_id, state)
    return state, teams

def add_team_to_active_league(guild_id, league_id, new_team_id):
    """Aktif veya waiting ligine yeni takım ekler ve fikstürü yeniden oluşturur."""
    from data_manager import save_league_state
    state = get_league_state(guild_id, league_id)
    if not state:
        return None, "Lig bulunamadı."
    if state['status'] == 'finished':
        return None, "Lig zaten tamamlandı."

    if new_team_id in state['registered_teams']:
        return None, "Bu takım zaten ligde kayıtlı."

    league_data = get_league_by_id(league_id)
    new_team = next((t for t in league_data['teams'] if t['id'] == new_team_id), None)
    if not new_team:
        return None, "Takım lig verisinde bulunamadı."

    # Yeni takımı ekle
    state['registered_teams'].append(new_team_id)
    state['standings'][new_team_id] = {
        'team_id': new_team_id, 'team_name': new_team.get('shortName', new_team['name']),
        'played': 0, 'won': 0, 'drawn': 0, 'lost': 0,
        'goals_for': 0, 'goals_against': 0, 'goal_diff': 0, 'points': 0
    }

    # Tamamlanan maçları hesapla
    played_matches = set()
    for rnd in state['fixtures'][:state['current_round']]:
        for m in rnd['matches']:
            played_matches.add((m['home'], m['away']))

    # Yeni fikstür: yeni takımın diğer tüm takımlarla ev+deplasman maçları
    current_round = state['current_round']
    all_team_ids = state['registered_teams']
    existing_teams = [t for t in all_team_ids if t != new_team_id]

    new_matches = []
    for existing_id in existing_teams:
        # Zaten oynanmış mı kontrol et
        if (new_team_id, existing_id) not in played_matches:
            new_matches.append({'home': new_team_id, 'away': existing_id})
        if (existing_id, new_team_id) not in played_matches:
            new_matches.append({'home': existing_id, 'away': new_team_id})

    # Yeni maçları gelecek haftalara dağıt
    future_rounds = state['fixtures'][current_round:]
    # Her yeni maçı bir sonraki uygun haftaya ekle
    idx = 0
    for match in new_matches:
        if idx < len(future_rounds):
            future_rounds[idx]['matches'].append(match)
            idx = (idx + 1) % len(future_rounds)
        else:
            # Yeni hafta oluştur
            new_rnd = {'round': state['total_rounds'] + 1, 'matches': [match]}
            state['fixtures'].append(new_rnd)
            state['total_rounds'] += 1

    save_league_state(guild_id, league_id, state)
    return state, None

# ─── /start ──────────────────────────────────────────────────────────────────
async def cmd_start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text(
        "⚽ <b>Futbol Botuna Hoş Geldin!</b>\n\n"
        "Takımını seçerek ve lige katılarak başla:\n"
        "/takim — Takım bilgisi\n"
        "/rastgeletakim — Rastgele takım al 🎲\n\n"
        "Tüm komutlar için: /yardim",
        parse_mode='HTML'
    )

# ─── /takim ──────────────────────────────────────────────────────────────────
async def cmd_takim(update: Update, context: ContextTypes.DEFAULT_TYPE):
    my_team_id = get_user_team(gid(update), uid(update))
    if not my_team_id:
        return await update.message.reply_text(
            "⚽ <b>Takım Bilgisi</b>\n\n"
            "Henüz bir takım seçmedin.\n"
            "/rastgeletakim — Rastgele takım al 🎲\n"
            "/kadro [takım adı] — Kadro görüntüle\n"
            "/takimlar [lig_id] — Tüm takımlar\n\n"
            "<b>Manuel seçim için:</b> /takimsec &lt;takım adı&gt;", parse_mode='HTML')
    td = get_team_by_id(my_team_id)
    if not td:
        return await update.message.reply_text("❌ Takım bulunamadı.")
    team, league = td['team'], td['league']
    avg = round(sum(p.get('overall',70) for p in team['players']) / len(team['players'])) if team['players'] else 0
    await update.message.reply_text(
        f"{team.get('emoji','')} <b>{team['name']}</b>\n\n"
        f"🏆 Lig: {league.get('emoji','')} {league['name']}\n"
        f"🏟️ Stat: {team.get('stadium','')}\n"
        f"👔 Teknik Direktör: {team.get('manager','')}\n"
        f"👥 Kadro: {len(team['players'])} oyuncu\n"
        f"⭐ Ort. Güç: {avg} OVR\n"
        f"💰 Bütçe: €{team.get('budget',0)//1000000}M\n\n"
        f"/kadro — Kadroyu görüntüle\n/takimsec &lt;ad&gt; — Takım değiştir", parse_mode='HTML')

# ─── /takimsec (korundu, gizli kullanım için) ─────────────────────────────────
async def cmd_takimsec(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = ' '.join(context.args)
    if not query:
        return await update.message.reply_text("Kullanım: /takimsec &lt;takım adı&gt;\nÖrnek: /takimsec Manchester City", parse_mode='HTML')
    results = search_team(query)
    if not results:
        return await update.message.reply_text(f"❌ <b>{query}</b> bulunamadı. /takimlar ile listele.", parse_mode='HTML')
    team, league = results[0]['team'], results[0]['league']
    set_user_team(gid(update), uid(update), team['id'])
    await update.message.reply_text(
        f"✅ <b>Takımın Seçildi: {team.get('emoji','')} {team['name']}</b>\n\n"
        f"🏆 Lig: {league.get('emoji','')} {league['name']}\n"
        f"🏟️ Stat: {team.get('stadium','')}\n"
        f"👔 Teknik Direktör: {team.get('manager','')}\n"
        f"👥 Kadro: {len(team['players'])} oyuncu\n"
        f"💰 Bütçe: €{team.get('budget',0)//1000000}M\n\n"
        f"/antrenman ile antrenman yapmaya başla!", parse_mode='HTML')

# ─── /kadro ──────────────────────────────────────────────────────────────────
async def cmd_kadro(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = ' '.join(context.args)
    if query:
        results = search_team(query)
        if not results:
            return await update.message.reply_text(f"❌ <b>{query}</b> bulunamadı.", parse_mode='HTML')
        td = results[0]
    else:
        my_id = get_user_team(gid(update), uid(update))
        if not my_id:
            return await update.message.reply_text("❌ Önce takım seç: /takimsec &lt;takım adı&gt;", parse_mode='HTML')
        td = get_team_by_id(my_id)
        if not td:
            return await update.message.reply_text("❌ Takım verisi bulunamadı.")
    team, league = td['team'], td['league']
    pos_order = ['GK','CB','RB','LB','DM','CM','CAM','RW','LW','ST']
    pos_emoji = {'GK':'🧤','CB':'🛡️','RB':'🛡️','LB':'🛡️','CM':'⚙️','CAM':'🎯','DM':'🛡️','RW':'⚡','LW':'⚡','ST':'🔥'}
    by_pos = {}
    for p in team['players']:
        by_pos.setdefault(p.get('position','?'), []).append(p)
    msg = f"{team.get('emoji','')} <b>{team['name']} — Kadro</b>\n{league.get('emoji','')} {league['name']}\n\n"
    for pos in pos_order:
        players = by_pos.get(pos, [])
        if not players: continue
        msg += f"{pos_emoji.get(pos,'⚽')} <b>{pos}</b>\n"
        for p in players:
            msg += f"  • {p['name']} ({p.get('nationality','')}) — OVR: <b>{p.get('overall',0)}</b>\n"
        msg += '\n'
    if len(msg) > 4000:
        msg = msg[:4000] + '\n<i>...(kısaltıldı)</i>'
    await update.message.reply_text(msg, parse_mode='HTML')

# ─── /takimlar ───────────────────────────────────────────────────────────────
async def cmd_takimlar(update: Update, context: ContextTypes.DEFAULT_TYPE):
    league_id = context.args[0].lower() if context.args else None
    if not league_id:
        leagues = get_leagues()
        msg = "🌍 <b>Tüm Ligler</b>\n\n"
        for l in leagues:
            msg += f"{l.get('emoji','')} <b>{l['name']}</b> — <code>{l['id']}</code> ({len(l['teams'])} takım)\n"
        msg += "\nDetay için: /takimlar &lt;lig_id&gt;"
        return await update.message.reply_text(msg, parse_mode='HTML')
    league = get_league_by_id(league_id)
    if not league:
        return await update.message.reply_text(f"❌ <b>{league_id}</b> ligi bulunamadı.", parse_mode='HTML')
    msg = f"{league.get('emoji','')} <b>{league['name']} — Takımlar</b>\n\n"
    for t in league['teams']:
        msg += f"{t.get('emoji','')} <b>{t['name']}</b>\n   🏟️ {t.get('stadium','')} | 👔 {t.get('manager','')}\n\n"
    await update.message.reply_text(msg, parse_mode='HTML')

# ─── /antrenman ──────────────────────────────────────────────────────────────
async def cmd_antrenman(update: Update, context: ContextTypes.DEFAULT_TYPE):
    my_id = get_user_team(gid(update), uid(update))
    if not my_id:
        return await update.message.reply_text("❌ Önce takım seç: /takimsec &lt;takım adı&gt;", parse_mode='HTML')
    td = get_team_by_id(my_id)
    if not td:
        return await update.message.reply_text("❌ Takım bulunamadı.")
    team = td['team']
    sub = context.args[0].lower() if context.args else None

    if not sub:
        tr = get_training_data(gid(update), uid(update))
        cooldown_ms = COOLDOWN_HOURS * 3600
        last = tr.get('last_training', 0) if tr else 0
        can_train = (time.time() - last) > cooldown_ms
        msg = f"{team.get('emoji','')} <b>{team['name']} — Antrenman</b>\n\n"
        for key, t in TRAINING_TYPES.items():
            msg += f"{t['emoji']} /antrenman {key}\n   <i>{t['desc']}</i>\n\n"
        if can_train:
            msg += "✅ <b>Antrenman yapabilirsin!</b>"
        else:
            remaining = int((last + cooldown_ms - time.time()) / 60)
            msg += f"⏳ Sonraki antrenman: <b>{remaining} dakika</b> sonra"
        msg += f"\n📈 Toplam seans: {tr.get('total_sessions',0) if tr else 0}"
        return await update.message.reply_text(msg, parse_mode='HTML')

    tr = get_training_data(gid(update), uid(update)) or {'last_training': 0, 'total_sessions': 0, 'history': []}
    cooldown_ms = COOLDOWN_HOURS * 3600
    if (time.time() - tr.get('last_training', 0)) < cooldown_ms:
        remaining = int((tr['last_training'] + cooldown_ms - time.time()) / 60)
        return await update.message.reply_text(f"⏳ Antrenman için <b>{remaining} dakika</b> daha bekle!", parse_mode='HTML')
    if sub not in TRAINING_TYPES:
        return await update.message.reply_text("❌ Geçersiz tip. Kullanım: /antrenman", parse_mode='HTML')

    t = TRAINING_TYPES[sub]
    xp = t['xp'] + random.randint(0, 14)
    boosted = random.randint(3, 7)
    featured = random.sample(team['players'], min(3, len(team['players'])))
    featured_str = '\n'.join(f"• <b>{p['name']}</b> ({p.get('position','')})" for p in featured)
    results = ["🌟 Mükemmel antrenman! Takım harika form tutturdu.",
               "✅ İyi bir antrenman geçti. Oyuncular motivasyonlu.",
               "📈 Verimli çalışma. Bazı oyuncular dikkat çekti.",
               "⚽ Solid bir antrenman. Taktikler oturdu.",
               "💪 Fiziksel antrenman tamamlandı. Takım güçlendi."]

    tr['last_training'] = time.time()
    tr['total_sessions'] = tr.get('total_sessions', 0) + 1
    tr.setdefault('history', []).insert(0, {'type': sub, 'xp': xp, 'date': int(time.time())})
    tr['history'] = tr['history'][:20]
    save_training_data(gid(update), uid(update), tr)

    await update.message.reply_text(
        f"{t['emoji']} <b>{t['name']} Tamamlandı!</b>\n\n"
        f"{random.choice(results)}\n\n"
        f"⭐ XP: <b>+{xp} XP</b>\n"
        f"👥 Etkilenen: <b>{boosted} oyuncu</b>\n\n"
        f"🌟 <b>Öne Çıkanlar:</b>\n{featured_str}\n\n"
        f"⏳ Sonraki antrenman: {COOLDOWN_HOURS} saat sonra", parse_mode='HTML')

# ─── Transfer Komutları ───────────────────────────────────────────────────────
async def cmd_transfer(update: Update, context: ContextTypes.DEFAULT_TYPE):
    squad = get_user_squad(gid(update), uid(update))
    budget_m = round(squad['budget'] / 1_000_000, 1)
    player_count = len(squad['players'])
    await update.message.reply_text(
        "💰 <b>Transfer Sistemi</b>\n\n"
        f"🏦 Bütçen: <b>€{budget_m}M</b>\n"
        f"🗂 Kadro: <b>{player_count} oyuncu</b>\n\n"
        "/transferara &lt;oyuncu adı&gt; — Oyuncu ara\n"
        "/satin &lt;oyuncu adı&gt; — Oyuncu satın al\n"
        "/sat &lt;oyuncu adı&gt; — Oyuncunu sat\n"
        "/kadrom — Kendi kadromu göster\n"
        "/pazar — Günlük transfer pazarı\n"
        "/serbest — Serbest oyuncu havuzu 🆓\n"
        "/oyuncu &lt;oyuncu adı&gt; — Oyuncu detayı\n\n"
        "<b>Örnek:</b> /satin Haaland", parse_mode='HTML')

async def cmd_transferara(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = ' '.join(context.args)
    if not query:
        return await update.message.reply_text("Kullanım: /transferara &lt;oyuncu adı&gt;", parse_mode='HTML')
    results = search_player(query)
    if not results:
        return await update.message.reply_text(f"❌ <b>{query}</b> için sonuç bulunamadı.", parse_mode='HTML')
    shown = results[:10]
    msg = f"🔍 <b>Transfer Araması: \"{query}\"</b>\n\n"
    for r in shown:
        p = r['player']
        val = estimate_value(p)
        msg += f"<b>{p['name']}</b> | {p.get('position','')} | OVR: {p.get('overall',0)} | {r['team'].get('emoji','')} {r['team']['shortName']} | 💰 €{val}M\n"
    if len(results) > 10:
        msg += f"\n<i>{len(results)} sonuç bulundu, ilk 10 gösteriliyor</i>"
    msg += "\n\n<i>Satın almak için: /satin &lt;oyuncu adı&gt;</i>"
    await update.message.reply_text(msg, parse_mode='HTML')

async def cmd_oyuncu(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = ' '.join(context.args)
    if not query:
        return await update.message.reply_text("Kullanım: /oyuncu &lt;oyuncu adı&gt;", parse_mode='HTML')
    results = search_player(query)
    if not results:
        return await update.message.reply_text(f"❌ <b>{query}</b> bulunamadı.", parse_mode='HTML')
    r = results[0]; p = r['player']; team = r['team']; league = r['league']
    val = estimate_value(p)
    squad = get_user_squad(gid(update), uid(update))
    owned = any(op['id'] == p['id'] for op in squad['players'])
    status = "✅ Kadronda" if owned else f"💰 Satın almak için: /satin {p['name']}"
    await update.message.reply_text(
        f"👤 <b>{p['name']}</b>\n\n"
        f"🏃 Mevki: <b>{p.get('position','')}</b>\n"
        f"🌍 Milliyet: {p.get('nationality','')}\n"
        f"🎂 Yaş: {p.get('age','')}\n"
        f"⭐ OVR: <b>{p.get('overall',0)}</b>\n"
        f"💰 Değer: €{val}M\n"
        f"💵 Maaş: £{p.get('wage',0)//1000}K/hafta\n"
        f"🏟️ Takım: {team.get('emoji','')} {team['name']}\n"
        f"🏆 Lig: {league.get('emoji','')} {league['name']}\n\n"
        f"{status}", parse_mode='HTML')

async def cmd_satin(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = ' '.join(context.args)
    if not query:
        return await update.message.reply_text("Kullanım: /satin &lt;oyuncu adı&gt;\nÖrnek: /satin Haaland", parse_mode='HTML')

    squad = get_user_squad(gid(update), uid(update))

    # Önce serbest oyuncularda ara
    ql = query.lower()
    fa_found = next((p for p in FREE_AGENT_POOL if ql in p['name'].lower()), None)

    if fa_found:
        val = estimate_value(fa_found)
        price = int(val * 1_000_000)
        if any(op['id'] == fa_found['id'] for op in squad['players']):
            return await update.message.reply_text(f"⚠️ <b>{fa_found['name']}</b> zaten kadronuzda!", parse_mode='HTML')
        if squad['budget'] < price:
            short = round((price - squad['budget']) / 1_000_000, 1)
            return await update.message.reply_text(
                f"❌ Yetersiz bütçe!\n\n"
                f"👤 {fa_found['name']} — €{val}M\n"
                f"💸 Bütçen: €{round(squad['budget']/1_000_000,1)}M\n"
                f"📉 Eksik: €{short}M", parse_mode='HTML')
        squad['budget'] -= price
        player_copy = dict(fa_found)
        player_copy['bought_for'] = val
        player_copy['from_team'] = 'Serbest'
        squad['players'].append(player_copy)
        save_user_squad(gid(update), uid(update), squad)
        return await update.message.reply_text(
            f"✅ <b>Serbest Oyuncu Transferi!</b>\n\n"
            f"🆓 <b>{fa_found['name']}</b> kadronuza katıldı!\n"
            f"🏃 Mevki: {fa_found.get('position','')} | ⭐ OVR: {fa_found.get('overall',0)}\n"
            f"💸 Ödenen: €{val}M\n"
            f"🏦 Kalan Bütçe: €{round(squad['budget']/1_000_000,1)}M", parse_mode='HTML')

    # Normal ligden ara
    results = search_player(query)
    if not results:
        return await update.message.reply_text(f"❌ <b>{query}</b> bulunamadı.\n\n💡 Serbest oyuncular için /serbest komutunu dene!", parse_mode='HTML')
    r = results[0]; p = r['player']; team = r['team']
    val = estimate_value(p)
    price = int(val * 1_000_000)
    if any(op['id'] == p['id'] for op in squad['players']):
        return await update.message.reply_text(f"⚠️ <b>{p['name']}</b> zaten kadronuzda!", parse_mode='HTML')
    if squad['budget'] < price:
        short = round((price - squad['budget']) / 1_000_000, 1)
        return await update.message.reply_text(
            f"❌ Yetersiz bütçe!\n\n"
            f"👤 {p['name']} — €{val}M\n"
            f"💸 Bütçen: €{round(squad['budget']/1_000_000,1)}M\n"
            f"📉 Eksik: €{short}M\n\n"
            f"Oyuncu sat: /sat &lt;oyuncu adı&gt;", parse_mode='HTML')
    squad['budget'] -= price
    player_copy = dict(p)
    player_copy['bought_for'] = val
    player_copy['from_team'] = team['name']
    squad['players'].append(player_copy)
    save_user_squad(gid(update), uid(update), squad)
    remaining = round(squad['budget'] / 1_000_000, 1)
    await update.message.reply_text(
        f"✅ <b>Transfer Tamamlandı!</b>\n\n"
        f"👤 <b>{p['name']}</b> kadronuza katıldı!\n"
        f"🏃 Mevki: {p.get('position','')} | ⭐ OVR: {p.get('overall',0)}\n"
        f"💸 Ödenen: €{val}M\n"
        f"🏦 Kalan Bütçe: €{remaining}M\n\n"
        f"/kadrom ile kadronuzu görüntüleyin", parse_mode='HTML')

async def cmd_sat(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = ' '.join(context.args)
    if not query:
        return await update.message.reply_text("Kullanım: /sat &lt;oyuncu adı&gt;\nÖrnek: /sat Haaland", parse_mode='HTML')
    squad = get_user_squad(gid(update), uid(update))
    if not squad['players']:
        return await update.message.reply_text("❌ Kadronuzda oyuncu yok. Satın almak için /satin kullanın.", parse_mode='HTML')
    ql = query.lower()
    found = next((p for p in squad['players'] if ql in p['name'].lower()), None)
    if not found:
        msg = f"❌ <b>{query}</b> kadronuzda bulunamadı.\n\n<b>Kadronuzdaki oyuncular:</b>\n"
        for p in squad['players']:
            msg += f"• {p['name']} ({p.get('position','')})\n"
        return await update.message.reply_text(msg, parse_mode='HTML')
    val = estimate_value(found)
    sell_price = int(val * 1_000_000 * 0.85)
    squad['players'].remove(found)
    squad['budget'] += sell_price
    squad.setdefault('sold', []).append({'name': found['name'], 'sold_for': val * 0.85})
    save_user_squad(gid(update), uid(update), squad)
    remaining = round(squad['budget'] / 1_000_000, 1)
    await update.message.reply_text(
        f"💸 <b>Oyuncu Satıldı!</b>\n\n"
        f"👤 <b>{found['name']}</b> satıldı\n"
        f"💰 Gelir: €{round(val*0.85, 1)}M (-%15 komisyon)\n"
        f"🏦 Yeni Bütçe: €{remaining}M\n\n"
        f"/transferara ile yeni oyuncu ara", parse_mode='HTML')

async def cmd_kadrom(update: Update, context: ContextTypes.DEFAULT_TYPE):
    squad = get_user_squad(gid(update), uid(update))
    budget_m = round(squad['budget'] / 1_000_000, 1)
    players = squad['players']
    if not players:
        return await update.message.reply_text(
            f"🗂 <b>Kadronuz Boş</b>\n\n"
            f"🏦 Bütçe: €{budget_m}M\n\n"
            f"Oyuncu almak için: /transferara veya /pazar veya /serbest", parse_mode='HTML')
    pos_order = ['GK','RB','CB','LB','CM','CAM','LW','RW','ST']
    by_pos = {}
    for p in players:
        pos = p.get('position', 'DİĞER')
        by_pos.setdefault(pos, []).append(p)
    total_val = round(sum(estimate_value(p) for p in players), 1)
    avg_ovr = round(sum(p.get('overall',70) for p in players) / len(players))
    msg = f"🗂 <b>Kadronuz</b> ({len(players)} oyuncu)\n"
    msg += f"🏦 Bütçe: €{budget_m}M | 💎 Kadro Değeri: €{total_val}M | ⭐ Ort: {avg_ovr} OVR\n\n"
    for pos in pos_order:
        if pos in by_pos:
            msg += f"<b>{pos}</b>\n"
            for p in by_pos[pos]:
                val = estimate_value(p)
                fa_tag = " 🆓" if p.get('from_team') == 'Serbest' else ""
                msg += f"  • {p['name']} OVR:{p.get('overall',0)} 💰€{val}M{fa_tag}\n"
    for pos, plist in by_pos.items():
        if pos not in pos_order:
            msg += f"<b>{pos}</b>\n"
            for p in plist:
                msg += f"  • {p['name']} OVR:{p.get('overall',0)}\n"
    msg += "\n/sat &lt;isim&gt; ile oyuncu sat"
    await update.message.reply_text(msg, parse_mode='HTML')

async def cmd_pazar(update: Update, context: ContextTypes.DEFAULT_TYPE):
    all_players = []
    for league in get_leagues():
        for team in league['teams']:
            for player in team.get('players', []):
                if 74 <= player.get('overall', 0) <= 87:
                    all_players.append({'player': player, 'team': team, 'league': league, 'value': estimate_value(player)})
    market = random.sample(all_players, min(8, len(all_players)))
    squad = get_user_squad(gid(update), uid(update))
    budget_m = round(squad['budget'] / 1_000_000, 1)
    msg = f"💰 <b>Transfer Pazarı — Günlük Teklifler</b>\n🏦 Bütçen: €{budget_m}M\n\n"
    for item in market:
        p = item['player']
        owned = "✅" if any(op['id'] == p['id'] for op in squad['players']) else ""
        msg += f"{owned}<b>{p['name']}</b> ({p.get('position','')}) OVR: {p.get('overall',0)}\n"
        msg += f"  {item['team'].get('emoji','')} {item['team']['shortName']} | 💰 €{item['value']}M\n\n"
    msg += "\n🆓 Serbest oyuncular için: /serbest\n<i>Satın almak için: /satin &lt;isim&gt;</i>"
    await update.message.reply_text(msg, parse_mode='HTML')

# ─── /serbest ────────────────────────────────────────────────────────────────
async def cmd_serbest(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Serbest oyuncu havuzunu listeler."""
    squad = get_user_squad(gid(update), uid(update))
    budget_m = round(squad['budget'] / 1_000_000, 1)
    msg = f"🆓 <b>Serbest Oyuncu Havuzu</b>\n🏦 Bütçen: €{budget_m}M\n\n"
    for p in FREE_AGENT_POOL:
        val = estimate_value(p)
        owned = "✅ " if any(op['id'] == p['id'] for op in squad['players']) else ""
        affordable = "💚" if squad['budget'] >= int(val * 1_000_000) else "🔴"
        msg += f"{owned}{affordable} <b>{p['name']}</b> ({p['position']}) OVR: {p['overall']} | €{val}M\n"
        msg += f"  🌍 {p['nationality']} | 🎂 {p['age']} yaş\n\n"
    msg += "\n<i>Satın almak için: /satin &lt;oyuncu adı&gt;</i>"
    await update.message.reply_text(msg, parse_mode='HTML')

# ─── /puan ───────────────────────────────────────────────────────────────────
async def cmd_puan(update: Update, context: ContextTypes.DEFAULT_TYPE):
    league_id = context.args[0].lower() if context.args else None
    if not league_id:
        leagues = get_leagues()
        msg = "📊 <b>Puan Durumu</b>\n\nLig belirtin:\n\n"
        for l in leagues:
            msg += f"{l.get('emoji','')} <code>/puan {l['id']}</code> — {l['name']}\n"
        return await update.message.reply_text(msg, parse_mode='HTML')
    state = get_league_state(gid(update), league_id)
    if not state:
        return await update.message.reply_text(f"❌ <b>{league_id}</b> ligi başlatılmamış.\n/ligbaslat {league_id}", parse_mode='HTML')
    sorted_s = sorted(state['standings'].values(), key=lambda t: (-t['points'], -t['goal_diff']))
    league_data = get_league_by_id(league_id)
    medals = ['🥇','🥈','🥉']
    status_txt = {'waiting':'⏳ Katılım bekleniyor', 'active':'🟢 Aktif', 'finished':'🏁 Tamamlandı', 'stopped':'⏹️ Durduruldu'}.get(state['status'], state['status'])
    msg = f"{league_data.get('emoji','🏆')} <b>{state['league_name']} — Puan Durumu</b>\n📅 Hafta {state['current_round']}/{state['total_rounds']} | {status_txt}\n\n"
    for i, t in enumerate(sorted_s):
        pos = medals[i] if i < 3 else f"{i+1}."
        gd = f"+{t['goal_diff']}" if t['goal_diff'] >= 0 else str(t['goal_diff'])
        msg += f"{pos} <b>{t['team_name']}</b> — <b>{t['points']}P</b>\n"
        msg += f"    {t['played']}O {t['won']}G {t['drawn']}B {t['lost']}M | {t['goals_for']}:{t['goals_against']} ({gd})\n"
    await update.message.reply_text(msg, parse_mode='HTML')

# ─── /sonuclar ───────────────────────────────────────────────────────────────
async def cmd_sonuclar(update: Update, context: ContextTypes.DEFAULT_TYPE):
    log = get_match_log(gid(update), 10)
    if not log:
        return await update.message.reply_text("❌ Henüz hiç maç oynanmadı.")
    msg = "📋 <b>Son Maç Sonuçları</b>\n\n"
    for m in log:
        date = datetime.fromtimestamp(m.get('timestamp',0)).strftime('%d.%m.%Y')
        hg, ag = m.get('home_goals',0), m.get('away_goals',0)
        arrow = '›' if hg > ag else '‹' if ag > hg else '='
        msg += f"<b>{m['home_team']} {hg}–{ag} {m['away_team']}</b> {arrow}  <i>{date}</i>\n"
    await update.message.reply_text(msg, parse_mode='HTML')

# ─── /fikstur ────────────────────────────────────────────────────────────────
async def cmd_fikstur(update: Update, context: ContextTypes.DEFAULT_TYPE):
    league_id = context.args[0].lower() if context.args else None
    if not league_id:
        leagues = get_leagues()
        msg = "📅 <b>Fikstür</b>\n\nLig belirtin:\n\n"
        for l in leagues:
            msg += f"{l.get('emoji','')} <code>/fikstur {l['id']}</code> — {l['name']}\n"
        return await update.message.reply_text(msg, parse_mode='HTML')
    state = get_league_state(gid(update), league_id)
    if not state:
        return await update.message.reply_text(f"❌ <b>{league_id}</b> ligi başlatılmamış.", parse_mode='HTML')
    league_data = get_league_by_id(league_id)
    next_round = state['current_round'] + 1
    show_rounds = state['fixtures'][next_round-1:next_round+2]
    if not show_rounds:
        return await update.message.reply_text("🏁 Fikstür tamamlandı.")
    msg = f"{league_data.get('emoji','')} <b>{state['league_name']} — Fikstür</b>\nMevcut Hafta: {state['current_round']}/{state['total_rounds']}\n\n"
    all_teams = {t['id']: t for t in league_data['teams']}
    for rnd in show_rounds:
        label = " (Sonraki)" if rnd['round'] == next_round else ""
        msg += f"<b>📅 Hafta {rnd['round']}{label}</b>\n"
        for match in rnd['matches']:
            ht = all_teams.get(match['home'])
            at = all_teams.get(match['away'])
            if ht and at:
                msg += f"  {ht.get('emoji','')} {ht.get('shortName', ht['name'])} vs {at.get('shortName', at['name'])} {at.get('emoji','')}\n"
        msg += '\n'
    await update.message.reply_text(msg, parse_mode='HTML')

# ─── /rastgeletakim ──────────────────────────────────────────────────────────
async def cmd_rastgeletakim(update: Update, context: ContextTypes.DEFAULT_TYPE):
    all_teams = []
    for league in get_leagues():
        for team in league['teams']:
            all_teams.append({'team': team, 'league': league})
    if not all_teams:
        return await update.message.reply_text("❌ Takım bulunamadı.")
    chosen = random.choice(all_teams)
    team, league = chosen['team'], chosen['league']
    set_user_team(gid(update), uid(update), team['id'])
    avg = round(sum(p.get('overall',70) for p in team['players']) / len(team['players'])) if team['players'] else 0
    squad = get_user_squad(gid(update), uid(update))
    squad['budget'] = team.get('budget', 50_000_000)
    save_user_squad(gid(update), uid(update), squad)
    await update.message.reply_text(
        f"🎲 <b>Rastgele Takım!</b>\n\n"
        f"{team.get('emoji','')} <b>{team['name']}</b>\n\n"
        f"🏆 Lig: {league.get('emoji','')} {league['name']}\n"
        f"🏟️ Stat: {team.get('stadium','')}\n"
        f"👔 Teknik Direktör: {team.get('manager','')}\n"
        f"👥 Kadro: {len(team['players'])} oyuncu\n"
        f"⭐ Ort. Güç: {avg} OVR\n"
        f"💰 Bütçe: €{team.get('budget',0)//1_000_000}M\n\n"
        f"Şans diliyoruz! 🍀", parse_mode='HTML')

# ─── Admin Komutları ──────────────────────────────────────────────────────────
async def cmd_admin(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not await is_admin(update, context):
        return await update.message.reply_text("❌ Yönetici yetkisi gerekli!")
    await update.message.reply_text(
        "⚙️ <b>Admin Komutları</b>\n\n"
        "/ligbaslat &lt;lig_id&gt; — Lig başlat (buton ile katılım)\n"
        "/ligdurdur &lt;lig_id&gt; — Ligi durdur\n"
        "/ligsifirla &lt;lig_id&gt; — Ligi sıfırla\n"
        "/ligler — Aktif ligleri göster\n"
        "/adminpuan &lt;lig_id&gt; — Puan durumu\n"
        "/simule — Manuel maç simülasyonu\n"
        "/kanal — Bu kanalı duyuru kanalı yap\n\n"
        "<b>Lig ID'leri:</b>\n"
        "<code>premier_league</code> | <code>la_liga</code> | <code>bundesliga</code>\n"
        "<code>serie_a</code> | <code>ligue_1</code> | <code>eredivisie</code> | <code>primeira_liga</code>\n"
        "<code>super_lig</code> 🇹🇷",
        parse_mode='HTML')

async def cmd_ligbaslat(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Admin: Lig başlatır ve katılım butonu gönderir."""
    if not await is_admin(update, context):
        return await update.message.reply_text("❌ Yönetici yetkisi gerekli!")
    league_id = context.args[0].lower() if context.args else None
    if not league_id:
        leagues = get_leagues()
        msg = "📋 <b>Mevcut Ligler:</b>\n\n"
        for l in leagues:
            msg += f"{l.get('emoji','')} <code>{l['id']}</code> — {l['name']}\n"
        msg += "\nKullanım: /ligbaslat &lt;lig_id&gt;"
        return await update.message.reply_text(msg, parse_mode='HTML')

    existing = get_league_state(gid(update), league_id)
    if existing and existing.get('status') in ('active', 'waiting'):
        return await update.message.reply_text(
            f"⚠️ Bu lig zaten aktif ya da katılım bekliyor!\nDurdurmak için: /ligdurdur {league_id}", parse_mode='HTML')

    league_data = get_league_by_id(league_id)
    if not league_data:
        return await update.message.reply_text(f"❌ <b>{league_id}</b> ligi bulunamadı.", parse_mode='HTML')

    # Ligi "waiting" durumunda başlat (sadece admin oluşturur, takımlar henüz boş)
    state = {
        'league_id': league_id,
        'league_name': league_data['name'],
        'status': 'waiting',
        'current_round': 0,
        'total_rounds': 0,
        'fixtures': [],
        'standings': {},
        'registered_teams': [],
        'participants': {},  # user_id -> team_id
        'started_at': int(time.time()),
        'last_match_day': None,
        'join_message_id': None
    }
    save_league_state(gid(update), league_id, state)

    keyboard = [[InlineKeyboardButton(f"⚽ Katıl!", callback_data=f"join_league:{league_id}")]]
    reply_markup = InlineKeyboardMarkup(keyboard)

    msg = await update.message.reply_text(
        f"🏆 <b>{league_data.get('emoji','')} {league_data['name']} Başlıyor!</b>\n\n"
        f"👥 <b>Katılmak için aşağıdaki butona bas!</b>\n\n"
        f"📌 Takımınızı seçmiş olmanız gerekiyor (/takimsec veya /rastgeletakim)\n"
        f"⏰ Admin ligi başlatana kadar katılım açık!\n\n"
        f"<i>Katılan takımlar buraya eklenecek...</i>\n\n"
        f"✅ <b>Katılanlar: 0 takım</b>",
        parse_mode='HTML',
        reply_markup=reply_markup
    )

    # Mesaj ID'sini kaydet
    state['join_message_id'] = msg.message_id
    save_league_state(gid(update), league_id, state)

async def callback_join_league(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Kullanıcı 'Katıl!' butonuna bastığında çalışır."""
    query = update.callback_query
    await query.answer()

    data = query.data  # "join_league:premier_league"
    league_id = data.split(':')[1]
    guild_id = str(query.message.chat_id)
    user_id = str(query.from_user.id)
    username = query.from_user.first_name or query.from_user.username or "Oyuncu"

    state = get_league_state(guild_id, league_id)
    if not state:
        return await query.answer("❌ Lig bulunamadı!", show_alert=True)
    if state['status'] not in ('waiting',):
        return await query.answer("❌ Katılım süresi doldu!", show_alert=True)

    # Kullanıcının takımını kontrol et
    team_id = get_user_team(guild_id, user_id)
    if not team_id:
        return await query.answer("❌ Önce takım seç! /takimsec veya /rastgeletakim", show_alert=True)

    td = get_team_by_id(team_id)
    if not td:
        return await query.answer("❌ Takım verisi bulunamadı!", show_alert=True)

    team = td['team']
    league_data = get_league_by_id(league_id)

    # Takım zaten kayıtlı mı?
    participants = state.setdefault('participants', {})
    if user_id in participants:
        return await query.answer(f"✅ Zaten kayıtlısın: {team['name']}", show_alert=True)

    # Takım ligde var mı?
    league_team_ids = [t['id'] for t in league_data['teams']]
    if team_id not in league_team_ids:
        return await query.answer(
            f"❌ {team['name']} bu ligde yok!\nLig: {league_data['name']}\n/takimlar {league_id} ile bu ligin takımlarını gör.",
            show_alert=True
        )

    # Takım zaten başka kullanıcı tarafından alınmış mı?
    if team_id in participants.values():
        return await query.answer(f"❌ Bu takım başka bir oyuncu tarafından alınmış!", show_alert=True)

    # Katıl
    participants[user_id] = team_id
    state['participants'] = participants

    # Eğer bu takım standings'de yoksa ekle
    if team_id not in state['standings']:
        state['standings'][team_id] = {
            'team_id': team_id, 'team_name': team.get('shortName', team['name']),
            'played': 0, 'won': 0, 'drawn': 0, 'lost': 0,
            'goals_for': 0, 'goals_against': 0, 'goal_diff': 0, 'points': 0
        }
    if team_id not in state['registered_teams']:
        state['registered_teams'].append(team_id)

    save_league_state(guild_id, league_id, state)

    # Katılanlar listesini güncelle
    joined_list = ""
    for uid_p, tid_p in participants.items():
        td_p = get_team_by_id(tid_p)
        if td_p:
            t_p = td_p['team']
            joined_list += f"{t_p.get('emoji','')} {t_p['name']}\n"

    keyboard = [[InlineKeyboardButton(f"⚽ Katıl!", callback_data=f"join_league:{league_id}")]]
    reply_markup = InlineKeyboardMarkup(keyboard)

    try:
        await query.edit_message_text(
            f"🏆 <b>{league_data.get('emoji','')} {league_data['name']} — Katılım Açık!</b>\n\n"
            f"👥 <b>Katılmak için aşağıdaki butona bas!</b>\n\n"
            f"📌 Takımınızı seçmiş olmanız gerekiyor\n"
            f"⏰ Admin ligi başlatana kadar katılım açık!\n\n"
            f"✅ <b>Katılanlar ({len(participants)} takım):</b>\n{joined_list}",
            parse_mode='HTML',
            reply_markup=reply_markup
        )
    except Exception:
        pass

    await context.bot.send_message(
        chat_id=query.message.chat_id,
        text=f"✅ <b>{username}</b> — {team.get('emoji','')} <b>{team['name']}</b> ile katıldı!",
        parse_mode='HTML'
    )

async def cmd_ligbaslat_start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Admin: Katılım dönemini bitir ve maçları başlat. /ligbaslat_start <lig_id>"""
    if not await is_admin(update, context):
        return await update.message.reply_text("❌ Yönetici yetkisi gerekli!")
    league_id = context.args[0].lower() if context.args else None
    if not league_id:
        return await update.message.reply_text("Kullanım: /ligbaslat_start &lt;lig_id&gt;", parse_mode='HTML')

    state = get_league_state(gid(update), league_id)
    if not state:
        return await update.message.reply_text("❌ Lig bulunamadı.")
    if state['status'] != 'waiting':
        return await update.message.reply_text("❌ Bu lig 'waiting' durumunda değil.")

    registered = state.get('registered_teams', [])
    if len(registered) < 2:
        return await update.message.reply_text("❌ En az 2 takım gerekli! Şu an: " + str(len(registered)))

    # Fikstür oluştur
    league_data = get_league_by_id(league_id)
    teams = [t for t in league_data['teams'] if t['id'] in registered]
    fixtures = generate_fixtures(teams)

    state['fixtures'] = fixtures
    state['total_rounds'] = len(fixtures)
    state['status'] = 'active'
    save_league_state(gid(update), league_id, state)

    team_list = '\n'.join(f"{t.get('emoji','')} {t['name']}" for t in teams)
    await update.message.reply_text(
        f"🚀 <b>{league_data.get('emoji','')} {state['league_name']} Başladı!</b>\n\n"
        f"🏟️ Takım Sayısı: {len(teams)}\n"
        f"📅 Toplam Hafta: {len(fixtures)}\n"
        f"⚡ Otomatik Maçlar: Günde 3 maç (08:00, 16:00, 00:00 TR)\n\n"
        f"<b>Katılan Takımlar:</b>\n{team_list}\n\n"
        f"📢 Duyuru için: /kanal",
        parse_mode='HTML'
    )

async def cmd_ligdurdur(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not await is_admin(update, context):
        return await update.message.reply_text("❌ Yönetici yetkisi gerekli!")
    league_id = context.args[0].lower() if context.args else None
    if not league_id:
        return await update.message.reply_text("Kullanım: /ligdurdur &lt;lig_id&gt;", parse_mode='HTML')
    state = get_league_state(gid(update), league_id)
    if not state:
        return await update.message.reply_text("❌ Bu lig bulunamadı.")
    state['status'] = 'stopped'
    save_league_state(gid(update), league_id, state)
    await update.message.reply_text(f"⏹️ <b>{state['league_name']}</b> durduruldu.", parse_mode='HTML')

async def cmd_ligsifirla(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not await is_admin(update, context):
        return await update.message.reply_text("❌ Yönetici yetkisi gerekli!")
    league_id = context.args[0].lower() if context.args else None
    if not league_id:
        return await update.message.reply_text("Kullanım: /ligsifirla &lt;lig_id&gt;", parse_mode='HTML')
    data = get_guild_data(gid(update))
    if 'leagues' in data and league_id in data['leagues']:
        del data['leagues'][league_id]
        save_guild_data(gid(update), data)
        return await update.message.reply_text(f"🔄 <b>{league_id}</b> ligi sıfırlandı.", parse_mode='HTML')
    await update.message.reply_text("❌ Lig bulunamadı.")

async def cmd_ligler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not await is_admin(update, context):
        return await update.message.reply_text("❌ Yönetici yetkisi gerekli!")
    data = get_guild_data(gid(update))
    active = list(data.get('leagues', {}).values())
    if not active:
        leagues = get_leagues()
        msg = "📋 <b>Başlatılabilir Ligler:</b>\n\n"
        for l in leagues:
            msg += f"{l.get('emoji','')} <code>{l['id']}</code> — {l['name']} ({len(l['teams'])} takım)\n"
        msg += "\n/ligbaslat &lt;id&gt; ile başlatabilirsin."
        return await update.message.reply_text(msg, parse_mode='HTML')
    msg = "🏆 <b>Aktif Ligler</b>\n\n"
    for s in active:
        status_emoji = {'active':'🟢','waiting':'⏳','stopped':'🔴','finished':'🏁'}.get(s['status'], '⚪')
        participant_count = len(s.get('participants', {}))
        msg += f"{status_emoji} <b>{s['league_name']}</b>\n   Durum: {s['status']} | Hafta: {s['current_round']}/{s['total_rounds']} | Katılımcı: {participant_count}\n\n"
    await update.message.reply_text(msg, parse_mode='HTML')

async def cmd_adminpuan(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not await is_admin(update, context):
        return await update.message.reply_text("❌ Yönetici yetkisi gerekli!")
    league_id = context.args[0].lower() if context.args else None
    if not league_id:
        return await update.message.reply_text("Kullanım: /adminpuan &lt;lig_id&gt;", parse_mode='HTML')
    state = get_league_state(gid(update), league_id)
    if not state:
        return await update.message.reply_text("❌ Bu lig bulunamadı.")
    sorted_s = sorted(state['standings'].values(), key=lambda t: (-t['points'], -t['goal_diff']))
    medals = ['🥇','🥈','🥉']
    msg = f"📊 <b>{state['league_name']} — Puan Durumu</b>\nHafta {state['current_round']}/{state['total_rounds']}\n\n"
    for i, t in enumerate(sorted_s):
        pos = medals[i] if i < 3 else f"{i+1}."
        gd = f"+{t['goal_diff']}" if t['goal_diff'] >= 0 else str(t['goal_diff'])
        msg += f"{pos} <b>{t['team_name']}</b> — {t['points']}P | {t['played']}O {t['won']}G {t['drawn']}B {t['lost']}M | {t['goals_for']}:{t['goals_against']} ({gd})\n"
    await update.message.reply_text(msg, parse_mode='HTML')

async def cmd_simule(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not await is_admin(update, context):
        return await update.message.reply_text("❌ Yönetici yetkisi gerekli!")
    await update.message.reply_text("⏳ Maç simülasyonu başlıyor...")
    app = context.application
    try:
        await simulate_match_day(app)
    except Exception as e:
        await update.message.reply_text(f"❌ Hata: {e}")

async def cmd_kanal(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not await is_admin(update, context):
        return await update.message.reply_text("❌ Yönetici yetkisi gerekli!")
    set_announce_channel(gid(update), str(update.effective_chat.id))
    await update.message.reply_text("✅ Bu kanal/grup duyuru kanalı olarak ayarlandı!\nMaç sonuçları buraya gönderilecek.")

# ─── /yardim ─────────────────────────────────────────────────────────────────
async def cmd_yardim(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text(
        "⚽ <b>Futbol Botu — Komutlar</b>\n\n"
        "👤 <b>Takım</b>\n"
        "/takim — Takım bilgisi\n"
        "/takimsec &lt;takım adı&gt; — Takım seç\n"
        "/rastgeletakim — Rastgele takım al 🎲\n"
        "/kadro [takım adı] — Kadroyu görüntüle\n"
        "/takimlar [lig_id] — Tüm takımlar\n\n"
        "🏋️ <b>Antrenman</b>\n"
        "/antrenman — Antrenman listesi\n"
        "/antrenman kondisyon | teknik | taktik | gucantrenman | atismapraktik\n\n"
        "💰 <b>Transfer</b>\n"
        "/transfer — Transfer menüsü ve bütçe\n"
        "/transferara &lt;oyuncu&gt; — Oyuncu ara\n"
        "/satin &lt;oyuncu&gt; — Oyuncu satın al ✅\n"
        "/sat &lt;oyuncu&gt; — Kadrodan oyuncu sat\n"
        "/kadrom — Kendi transfer kadromu gör\n"
        "/oyuncu &lt;oyuncu&gt; — Oyuncu detayı\n"
        "/pazar — Günlük transfer pazarı\n"
        "/serbest — Serbest oyuncu havuzu 🆓\n\n"
        "📊 <b>Lig &amp; Sonuçlar</b>\n"
        "/puan &lt;lig_id&gt; — Puan durumu\n"
        "/sonuclar — Son maç sonuçları\n"
        "/fikstur &lt;lig_id&gt; — Yaklaşan maçlar\n\n"
        "⚙️ <b>Admin</b>\n"
        "/ligbaslat &lt;lig_id&gt; — Katılım butonu çıkar\n"
        "/ligbaslat_start &lt;lig_id&gt; — Maçları başlat\n"
        "/ligdurdur &lt;lig_id&gt; — Ligi durdur\n"
        "/ligsifirla &lt;lig_id&gt; — Sıfırla\n"
        "/ligler — Aktif ligler\n"
        "/adminpuan &lt;lig_id&gt; — Puan tablosu\n"
        "/simule — Manuel maç simülasyonu\n"
        "/kanal — Duyuru kanalı ayarla\n\n"
        "🌍 <b>Lig ID'leri:</b>\n"
        "<code>premier_league</code> <code>la_liga</code> <code>bundesliga</code>\n"
        "<code>serie_a</code> <code>ligue_1</code> <code>eredivisie</code> <code>primeira_liga</code>\n"
        "<code>super_lig</code> 🇹🇷\n\n"
        "<i>⚡ Maçlar günde 3 kez: 08:00, 16:00, 00:00 (TR)</i>",
        parse_mode='HTML')

# ─── Zamanlayıcı ─────────────────────────────────────────────────────────────
async def scheduled_match(context: ContextTypes.DEFAULT_TYPE):
    print("⚽ Otomatik maç simülasyonu başlıyor...")
    await simulate_match_day(context.application)

# ─── Ana fonksiyon ────────────────────────────────────────────────────────────
def main():
    app = Application.builder().token(TOKEN).build()

    # Komutları kaydet
    commands = [
        ('start', cmd_start), ('takim', cmd_takim), ('takimsec', cmd_takimsec),
        ('rastgeletakim', cmd_rastgeletakim),
        ('kadro', cmd_kadro), ('takimlar', cmd_takimlar),
        ('antrenman', cmd_antrenman),
        ('transfer', cmd_transfer), ('transferara', cmd_transferara),
        ('satin', cmd_satin), ('sat', cmd_sat), ('kadrom', cmd_kadrom),
        ('oyuncu', cmd_oyuncu), ('pazar', cmd_pazar), ('serbest', cmd_serbest),
        ('puan', cmd_puan), ('sonuclar', cmd_sonuclar),
        ('fikstur', cmd_fikstur),
        ('admin', cmd_admin), ('ligbaslat', cmd_ligbaslat),
        ('ligbaslat_start', cmd_ligbaslat_start),
        ('ligdurdur', cmd_ligdurdur), ('ligsifirla', cmd_ligsifirla),
        ('ligler', cmd_ligler), ('adminpuan', cmd_adminpuan),
        ('simule', cmd_simule), ('kanal', cmd_kanal),
        ('yardim', cmd_yardim),
    ]
    for name, handler in commands:
        app.add_handler(CommandHandler(name, handler))

    # Callback handler (buton basımları)
    app.add_handler(CallbackQueryHandler(callback_join_league, pattern=r'^join_league:'))

    # Zamanlanmış maçlar: Günde 3 kez — 08:00, 16:00, 00:00 TR (UTC+3)
    # UTC karşılıkları: 05:00, 13:00, 21:00
    import datetime as dt
    job_queue = app.job_queue
    job_queue.run_daily(scheduled_match, time=dt.time(5, 0, tzinfo=dt.timezone.utc))   # TR 08:00
    job_queue.run_daily(scheduled_match, time=dt.time(13, 0, tzinfo=dt.timezone.utc))  # TR 16:00
    job_queue.run_daily(scheduled_match, time=dt.time(21, 0, tzinfo=dt.timezone.utc))  # TR 00:00

    print("✅ Bot başlatıldı!")
    app.run_polling(drop_pending_updates=True)

if __name__ == '__main__':
    main()
