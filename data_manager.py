import json
import os

DATA_DIR = os.path.join(os.path.dirname(__file__), '..', 'data_store')


def ensure_dir():
    os.makedirs(DATA_DIR, exist_ok=True)


def get_guild_data(guild_id):
    ensure_dir()
    path = os.path.join(DATA_DIR, f"guild_{guild_id}.json")
    if not os.path.exists(path):
        default = {
            "guildId": guild_id,
            "leagues": {},
            "userTeams": {},
            "trainingSessions": {},
            "matchLog": [],
            "announceChannel": None,
            "createdAt": __import__('time').time()
        }
        with open(path, 'w', encoding='utf-8') as f:
            json.dump(default, f, ensure_ascii=False, indent=2)
        return default
    with open(path, 'r', encoding='utf-8') as f:
        return json.load(f)


def save_guild_data(guild_id, data):
    ensure_dir()
    path = os.path.join(DATA_DIR, f"guild_{guild_id}.json")
    with open(path, 'w', encoding='utf-8') as f:
        json.dump(data, f, ensure_ascii=False, indent=2)


def get_all_guild_ids():
    ensure_dir()
    ids = []
    for fname in os.listdir(DATA_DIR):
        if fname.startswith('guild_') and fname.endswith('.json'):
            ids.append(fname.replace('guild_', '').replace('.json', ''))
    return ids


def get_user_team(guild_id, user_id):
    data = get_guild_data(guild_id)
    return data.get("userTeams", {}).get(str(user_id))


def set_user_team(guild_id, user_id, team_id):
    data = get_guild_data(guild_id)
    data.setdefault("userTeams", {})[str(user_id)] = team_id
    save_guild_data(guild_id, data)


def get_league_state(guild_id, league_id):
    data = get_guild_data(guild_id)
    return data.get("leagues", {}).get(league_id)


def save_league_state(guild_id, league_id, state):
    data = get_guild_data(guild_id)
    data.setdefault("leagues", {})[league_id] = state
    save_guild_data(guild_id, data)


def add_match_to_log(guild_id, match_result):
    data = get_guild_data(guild_id)
    data.setdefault("matchLog", []).insert(0, match_result)
    data["matchLog"] = data["matchLog"][:100]
    save_guild_data(guild_id, data)


def get_match_log(guild_id, limit=20):
    data = get_guild_data(guild_id)
    return data.get("matchLog", [])[:limit]


def set_announce_channel(guild_id, channel_id):
    data = get_guild_data(guild_id)
    data["announceChannel"] = str(channel_id)
    save_guild_data(guild_id, data)


def get_announce_channel(guild_id):
    data = get_guild_data(guild_id)
    return data.get("announceChannel")


def get_training_data(guild_id, user_id):
    data = get_guild_data(guild_id)
    return data.get("trainingSessions", {}).get(str(user_id))


def save_training_data(guild_id, user_id, training_data):
    data = get_guild_data(guild_id)
    data.setdefault("trainingSessions", {})[str(user_id)] = training_data
    save_guild_data(guild_id, data)
