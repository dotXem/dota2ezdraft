import asyncio
import aiohttp
import yaml
import json
import time

STRATZ_API_TOKEN = "eyJhbGciOiJIUzI1NiIsInR5cCI6IkpXVCJ9.eyJTdWJqZWN0IjoiYTEyYTYzYjUtOWI2My00OThkLThlZjEtOGNhZmJiNDliZDY1IiwiU3RlYW1JZCI6IjM2MzM5Mjk3IiwibmJmIjoxNzAxNTExNDU2LCJleHAiOjE3MzMwNDc0NTYsImlhdCI6MTcwMTUxMTQ1NiwiaXNzIjoiaHR0cHM6Ly9hcGkuc3RyYXR6LmNvbSJ9.Nub3VZ58_I-jSZkfca6WI8TVNZbeDmNhjwgxK9xuyGM"

# reduce threshold because we don't have all tokens available in stratz dashboard
MAX_CALLS_PER_SECOND = 10 #20
MAX_CALLS_PER_MINUTE = 200 #250

HEROES = ['Witch Doctor', 'Spectre', 'Chaos Knight', 'Wraith King', 'Slardar',
 'Necrophos', 'Sand King', 'Lone Druid', 'Kunkka', 'Treant Protector', 'Jakiro',
 'Arc Warden', 'Phantom Lancer', 'Warlock', 'Meepo', 'Silencer', 'Abaddon',
 'Spirit Breaker', 'Zeus', 'Outworld Devourer', 'Ancient Apparition',
 'Shadow Shaman', 'Riki', 'Oracle', 'Lich', 'Muerta', 'Ogre Magi',
 'Centaur Warrunner', 'Nyx Assassin', 'Troll Warlord', 'Venomancer', 'Undying',
 'Axe', 'Clinkz', 'Naga Siren', 'Night Stalker', 'Visage', 'Vengeful Spirit',
 'Anti-Mage', 'Viper', 'Lifestealer', 'Grimstroke', 'Legion Commander',
 'Sniper', 'Bristleback', 'Skywrath Mage', 'Elder Titan', 'Io', 'Shadow Fiend',
 'Bounty Hunter', "Nature's Prophet", 'Weaver', 'Dazzle', 'Crystal Maiden',
 'Huskar', 'Omniknight', 'Tinker', 'Luna', 'Earthshaker', 'Slark', 'Underlord',
 'Drow Ranger', 'Bloodseeker', 'Chen', 'Dark Seer', 'Primal Beast',
 'Queen of Pain', 'Bane', 'Pugna', 'Brewmaster', 'Invoker', 'Pudge',
 'Juggernaut', 'Dawnbreaker', 'Disruptor', 'Void Spirit', 'Faceless Void',
 'Hoodwink', 'Marci', 'Razor', 'Winter Wyvern', 'Phoenix', 'Dark Willow',
 'Clockwerk', 'Phantom Assassin', 'Earth Spirit', 'Mirana', 'Dragon Knight',
 'Lycan', 'Ursa', 'Medusa', 'Death Prophet', 'Lina', 'Tidehunter', 'Gyrocopter',
 'Windranger', 'Alchemist', 'Sven', 'Techies', 'Enigma', 'Puck', 'Storm Spirit',
 'Templar Assassin', 'Leshrac', 'Shadow Demon', 'Morphling', 'Lion', 'Magnus',
 'Tusk', 'Monkey King', 'Keeper of the Light', 'Mars', 'Snapfire',
 'Broodmother', 'Doom', 'Beastmaster', 'Tiny', 'Timbersaw', 'Enchantress',
 'Rubick', 'Pangolier', 'Ember Spirit', 'Terrorblade', 'Batrider', "Ringmaster"]

async def fetch_hero_data(session, hero_id, stratz_id_to_hero, query):
    url = "https://api.stratz.com/graphql"
    headers = {
        'Content-Type': 'application/json',
        'Authorization': f'Bearer {STRATZ_API_TOKEN}',
    }
    payload = json.dumps({'query': query.replace("{hero_id}", str(hero_id))})

    async with session.post(url, headers=headers, data=payload) as response:
        if response.status == 200:
            result = await response.json()
            try:
                result_data = result["data"]["heroStats"]["heroVsHeroMatchup"]["disadvantage"][0]
                hero = stratz_id_to_hero[hero_id]
                data = {
                    hero: {
                        "matchup_disadvantage": {
                            stratz_id_to_hero[matchup["heroId2"]]: matchup["synergy"]
                            for matchup in result_data["vs"]
                        },
                        "matchup_winrate": {
                            stratz_id_to_hero[matchup["heroId2"]]: matchup["winsAverage"]
                            for matchup in result_data["vs"]
                        },
                        "synergy_disadvantage": {
                            stratz_id_to_hero[matchup["heroId2"]]: matchup["synergy"]
                            for matchup in result_data["with"]
                        },
                        "synergy_winrate": {
                            stratz_id_to_hero[matchup["heroId2"]]: matchup["winsAverage"]
                            for matchup in result_data["with"]
                        },
                        "winrate": result_data["vs"][0]["winRateHeroId1"]
                    }
                }
                return data
            except (KeyError, IndexError) as e:
                print(f"Error processing data for hero ID {hero_id}: {e}")
                return {}
        else:
            print(f"Error: {response.status} - {await response.text()}")
            return {}

async def get_data_from_stratz():
    with open("stratz_hero_to_id.yaml", "r") as file:
        stratz_hero_to_id = yaml.load(file, Loader=yaml.FullLoader)

    stratz_id_to_hero = {id: hero for hero, id in stratz_hero_to_id.items()}

    hero_ids = [stratz_hero_to_id[hero] for hero in HEROES]

    # heroVsHeroMatchup(heroId: {hero_id}, bracketBasicIds: DIVINE_IMMORTAL) {
    query = """
    {
        heroStats {
            heroVsHeroMatchup(heroId: {hero_id}) {
                disadvantage {
                    vs {
                        heroId1
                        heroId2
                        winsAverage
                        winRateHeroId2
                        winRateHeroId1
                        winCount
                        matchCount
                        synergy
                    }
                    with {
                        heroId1
                        heroId2
                        winsAverage
                        winRateHeroId2
                        winRateHeroId1
                        winCount
                        matchCount
                        synergy
                    }
                }
            }
        }
    }
    """

    data = {}

    chunk_size = MAX_CALLS_PER_SECOND  
    chunks = [hero_ids[i:i + chunk_size] for i in range(0, len(hero_ids), chunk_size)]

    async with aiohttp.ClientSession() as session:
        total_requests = 0
        start_minute = time.time()

        for chunk in chunks:
            start_time = time.time()
            tasks = []
            for hero_id in chunk:
                task = asyncio.create_task(fetch_hero_data(session, hero_id, stratz_id_to_hero, query))
                tasks.append(task)

            # Wait for all tasks in the current chunk to complete
            results = await asyncio.gather(*tasks)

            for hero_data in results:
                data.update(hero_data)

            total_requests += len(chunk)

            # Enforce per-minute rate limit
            elapsed_minute = time.time() - start_minute
            if total_requests >= MAX_CALLS_PER_MINUTE:
                if elapsed_minute < 60:
                    sleep_time = 60 - elapsed_minute
                    print(f"Reached {MAX_CALLS_PER_MINUTE} requests in {elapsed_minute:.2f} seconds. Sleeping for {sleep_time:.2f} seconds.")
                    await asyncio.sleep(sleep_time)
                total_requests = 0
                start_minute = time.time()

            # Enforce per-second rate limit
            elapsed = time.time() - start_time
            if elapsed < 1:
                await asyncio.sleep(1 - elapsed)

    return data

if __name__ == '__main__':
    data = asyncio.run(get_data_from_stratz())
    print(data)