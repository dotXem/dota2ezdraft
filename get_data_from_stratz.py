import yaml
import json
import time
import datetime
import calendar
import requests
import os
from dotenv import load_dotenv

load_dotenv()

STRATZ_API_URL = "https://api.stratz.com/graphql"
STRATZ_API_TOKEN = os.environ["STRATZ_API_TOKEN"]

# reduce threshold because we don't have all tokens available in stratz dashboard
MAX_CALLS_PER_SECOND = 1
MAX_CALLS_PER_MINUTE = 100 #250

with open("stratz_hero_to_id.yaml", "r") as file:
    STRATZ_HERO_TO_ID = yaml.load(file, Loader=yaml.FullLoader)
STRATZ_ID_TO_HERO = {id: hero for hero, id in STRATZ_HERO_TO_ID.items()}
HEROES = list(STRATZ_ID_TO_HERO.values())

BRACKETS = [
    ["DIVINE", "IMMORTAL"],
    ["ANCIENT", "LEGEND"],
    ["CRUSADER", "ARCHON"],
    ["GUARDIAN", "HERALD"]
]
HEADERS = {
    'Content-Type': 'application/json',
    'Authorization': f'Bearer {STRATZ_API_TOKEN}',
    'User-Agent': "STRATZ_API" 
}

def fetch_hero_data(session, hero_id, query):
    payload = json.dumps({'query': query.replace("{hero_id}", str(hero_id))})

    response = session.post(STRATZ_API_URL, headers=HEADERS, data=payload)
    if response.status_code == 200:
        result = response.json()
        try:
            result_data = result["data"]["heroStats"]["heroVsHeroMatchup"]["disadvantage"][0]
            hero = STRATZ_ID_TO_HERO[hero_id]
            data = {
                hero: {
                    "matchup_winrate": {
                        STRATZ_ID_TO_HERO[matchup["heroId2"]]: matchup["winsAverage"]
                        for matchup in result_data["vs"]
                        if matchup["heroId2"] in STRATZ_ID_TO_HERO
                    },
                    "synergy_winrate": {
                        STRATZ_ID_TO_HERO[matchup["heroId2"]]: matchup["winsAverage"]
                        for matchup in result_data["with"]
                        if matchup["heroId2"] in STRATZ_ID_TO_HERO
                    },
                    "winrate": result_data["vs"][0]["winRateHeroId1"]
                }
            }
            return data
        except (KeyError, IndexError) as e:
            print(f"Error processing data for hero ID {hero_id}: {e}")
            return {}
    else:
        print(f"Error: {response.status_code} - {response.text}")
        return {}

def get_matchup_data_from_stratz(session):
    hero_ids = list(STRATZ_ID_TO_HERO.keys())

    query = """
    {
        heroStats {
            heroVsHeroMatchup(heroId: {hero_id}, week: {week}) {
                disadvantage {
                    vs {
                        heroId2
                        winsAverage
                        winRateHeroId1
                    }
                    with {
                        heroId2
                        winsAverage
                        winRateHeroId1
                    }
                }
            }
        }
    }
    """

    week_long = get_thursday_before_last_thursday_unix_timestamp() # ensure we have a full week of data available
    query = query.replace("{week}", str(week_long))

    data = {}

    total_requests = 0
    start_minute = time.time()

    for hero_id in hero_ids:
        start_time = time.time()

        hero_data = fetch_hero_data(session, hero_id, query)
        data.update(hero_data)

        total_requests += 1

        # Enforce per-minute rate limit
        elapsed_minute = time.time() - start_minute
        if total_requests >= MAX_CALLS_PER_MINUTE:
            if elapsed_minute < 60:
                sleep_time = 60 - elapsed_minute
                print(f"Reached {MAX_CALLS_PER_MINUTE} requests in {elapsed_minute:.2f} seconds. Sleeping for {sleep_time:.2f} seconds.")
                time.sleep(sleep_time)
            total_requests = 0
            start_minute = time.time()

        # Enforce per-second rate limit
        elapsed = time.time() - start_time
        if elapsed < 1:
            time.sleep(1 - elapsed)

    return data

def get_data_from_stratz():
    session = requests.Session()
    data = get_matchup_data_from_stratz(session)

    winrates_per_bracket = get_winrates_per_bracket(session)
    for hero, hero_data in data.items():
        hero_data["winrate_brackets"] = {
            bracket: winrates_per_bracket[bracket][hero]
            for bracket in winrates_per_bracket
        }

    hero_per_position = get_hero_per_position(session)
    for hero, hero_data in data.items():
        hero_data["positions"] = hero_per_position[hero]

    return data

def get_thursday_before_last_thursday_unix_timestamp():
    today = datetime.date.today()

    days_since_last_thursday = (today.weekday() - 3) % 7
    last_thursday = today - datetime.timedelta(days=days_since_last_thursday)

    thursday_before_last = last_thursday - datetime.timedelta(days=7)

    thursday_before_last_datetime = datetime.datetime.combine(thursday_before_last, datetime.time(0, 0, 0))

    unix_timestamp = calendar.timegm(thursday_before_last_datetime.timetuple())

    return unix_timestamp

def get_hero_per_position(session):    
    query = """
        {
            heroStats {
                stats(groupByPosition: true, week: {week}) {
                heroId
                position
                matchCount
                winCount                
                }
            }
        }
    """

    week_long = get_thursday_before_last_thursday_unix_timestamp() # ensure we have a full week of data available
    query = query.replace("{week}", str(week_long))
    
    payload = json.dumps({'query': query})

    time.sleep(1)
    response = session.post(STRATZ_API_URL, headers=HEADERS, data=payload)

    data = response.json()

    hero_position_counts = {}
    for stat in data["data"]["heroStats"]["stats"]:
        hero_id = stat["heroId"]
        position = stat["position"]
        match_count = stat["matchCount"]

        if hero_id not in hero_position_counts:
            hero_position_counts[hero_id] = {"totalMatches": 0, "positions": {}}
        hero_position_counts[hero_id]["totalMatches"] += match_count
        if position not in hero_position_counts[hero_id]["positions"]:
            hero_position_counts[hero_id]["positions"][position] = 0
        hero_position_counts[hero_id]["positions"][position] += match_count


    hero_positions = {}
    for hero_id in hero_position_counts:
        if hero_id not in STRATZ_ID_TO_HERO:
            continue
        hero_name = STRATZ_ID_TO_HERO[hero_id]
        hero_positions[hero_name] = []

        total_matches = hero_position_counts[hero_id]["totalMatches"]
        positions = hero_position_counts[hero_id]["positions"]
        for position in positions:
            percentage = positions[position] / total_matches
            if percentage >= 0.10:
                hero_positions[hero_name].append(position)

    return hero_positions

def get_winrates_per_bracket(session):
    winrates = {}
    for bracket in BRACKETS:
        query = """
        {
            heroStats {
                winWeek(bracketIds: {bracket}, take:1) {
                    heroId
                    matchCount
                    winCount
                    week
                }
            }
        }
        """
        bracket_str = "[" + ",".join(bracket) + "]"
        query = query.replace("{bracket}", bracket_str)

        payload = json.dumps({'query': query})

        time.sleep(1)
        response = session.post(STRATZ_API_URL, headers=HEADERS, data=payload)

        data = response.json()

        winrates_for_bracket = {}
        for hero_data in data["data"]["heroStats"]["winWeek"]:
            hero_id = hero_data["heroId"]
            if hero_id not in STRATZ_ID_TO_HERO:
                continue
            hero_name = STRATZ_ID_TO_HERO[hero_id]
            winrate = hero_data["winCount"] / hero_data["matchCount"]
            winrates_for_bracket[hero_name] = winrate

        winrates[bracket_str] = winrates_for_bracket
    return winrates

# def push_new_data_to_gcs(data):
#     nb_fetched_heroes = len(data.keys())
#     success = nb_fetched_heroes == len(HEROES)

#     if success:
#         yaml_str = yaml.dump(data)
#         date = str(datetime.datetime.now().date())
#         file_path = f'heroes-ezdraft/data/{date}.yaml'
        
#         try:
#             with conn.fs.open(file_path, 'w') as f:
#                 f.write(yaml_str)
#         except:
#             print("An error occurred while writing to GCS.")

if __name__ == '__main__':
    data = get_data_from_stratz()
    # data = get_winrates_per_bracket()

    date = str(datetime.datetime.now().date())
    with open(f"{date}.yaml", "w") as file:
        yaml.dump(data, file)

    print(data)