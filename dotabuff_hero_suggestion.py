import numpy as np
import sys, os
SCRIPT_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.append(os.path.dirname(SCRIPT_DIR))
 

from webdriver_manager.chrome import ChromeDriverManager
from selenium import webdriver
import time
from lxml import html, etree
import yaml 
import pandas as pd
import json, requests


from selenium import webdriver
from selenium.webdriver.chrome.options import Options

STRATZ_API_TOKEN = "eyJhbGciOiJIUzI1NiIsInR5cCI6IkpXVCJ9.eyJTdWJqZWN0IjoiYTEyYTYzYjUtOWI2My00OThkLThlZjEtOGNhZmJiNDliZDY1IiwiU3RlYW1JZCI6IjM2MzM5Mjk3IiwibmJmIjoxNzAxNTExNDU2LCJleHAiOjE3MzMwNDc0NTYsImlhdCI6MTcwMTUxMTQ1NiwiaXNzIjoiaHR0cHM6Ly9hcGkuc3RyYXR6LmNvbSJ9.Nub3VZ58_I-jSZkfca6WI8TVNZbeDmNhjwgxK9xuyGM"

heroes = ['Witch Doctor', 'Spectre', 'Chaos Knight', 'Wraith King', 'Slardar',
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
 'Rubick', 'Pangolier', 'Ember Spirit', 'Terrorblade', 'Batrider']

import logging
logging.getLogger().setLevel(logging.INFO)
logging.basicConfig(
    format='%(asctime)s %(levelname)-8s %(message)s',
    level=logging.INFO,
    datefmt='%Y-%m-%d %H:%M:%S')

def get_page_from_dotabuff(driver, url):
    logging.info("Fetching URL...")
    driver.get(url)
    time.sleep(1500)
    logging.info("Parsing page content...")
    html_content = driver.execute_script("return document.documentElement.innerHTML;")
    tree = html.fromstring(html_content)
    return tree

def get_data_from_stratz():
    with open("stratz_hero_to_id.yaml", "r") as file:
        stratz_hero_to_id = yaml.load(file, Loader=yaml.FullLoader)

    stratz_id_to_hero = {
        id:hero for hero, id in stratz_hero_to_id.items()
    }

    querry = """
    {
        heroStats {
            heroVsHeroMatchup(heroId: {hero_id}, bracketBasicIds: DIVINE_IMMORTAL) {
                disadvantage {
                    heroId
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

    for hero in heroes:
        print(f"Collecting {hero} data...")
        hero_id = stratz_hero_to_id[hero]

        headers = {
            'Content-Type': 'application/json',
            'Authorization': f'Bearer {STRATZ_API_TOKEN}',
        }

        payload = json.dumps({'query': querry.replace("{hero_id}", str(hero_id))
        })

        response = requests.post("https://api.stratz.com/graphql", headers=headers, data=payload)

        if response.status_code == 200:
            result = response.json()
        else:
            print(f"Error: {response.status_code} - {response.text}")

        result = result["data"]["heroStats"]["heroVsHeroMatchup"]["disadvantage"][0]
        

        data[hero] = {
            "matchup_disadvantage": {
                stratz_id_to_hero[matchup["heroId2"]] :  matchup["synergy"]
                for matchup in result["vs"]
            },
            "matchup_winrate": {
                stratz_id_to_hero[matchup["heroId2"]]  : matchup["winsAverage"]
                for matchup in result["vs"]
            },            
            "synergy_disadvantage": {
                stratz_id_to_hero[matchup["heroId2"]]  : matchup["synergy"]
                for matchup in result["with"]
            },
            "synergy_winrate": {
                stratz_id_to_hero[matchup["heroId2"]]  : matchup["winsAverage"]
                for matchup in result["with"]
            },
            "winrate": result["vs"][0]["winRateHeroId1"]
        }

        time.sleep(1)

    return data

def get_page_from_stratz(driver, url):
    logging.info("Fetching URL...")
    driver.get(url)
    time.sleep(5)
    logging.info("Parsing page content...")
    html_content = driver.execute_script("return document.documentElement.innerHTML;")
    tree = html.fromstring(html_content)
    return tree

def get_winrate_data(driver):
    tree = get_page_from_dotabuff(driver, "https://www.dotabuff.com/heroes/winning")
    divs = tree.xpath("//table[@class='sortable']//tbody//tr//td")
    attribs = [div.attrib["data-value"] for div in divs]
    attribs = np.reshape(attribs, (-1, 5))
    heroes_wr = attribs[:, 0]
    heroes_wr[np.where(heroes_wr == "Outworld Destroyer")[0][0]] = "Outworld Devourer"
    heroes_wr = heroes_wr.tolist()
    winrates = attribs[:, 2].astype(float) / 100
    winrates = winrates.tolist()
    winrate_data = {
        hero:winrate
        for hero, winrate in zip(heroes_wr, winrates)
    }

    # tree = get_page_from_dotabuff(driver, "https://www.dotabuff.com/heroes/meta?view=played&metric=rating_bracket")
    # divs = tree.xpath("//table[@class='sortable no-arrows r-tab-enabled']//tbody//tr//td")
    # attribs = [div.attrib["data-value"] for div in divs]
    # attribs = np.reshape(attribs, (-1, 12))
    # heroes_wr = attribs[:, 0]
    # heroes_wr[np.where(heroes_wr == "Outworld Destroyer")[0][0]] = "Outworld Devourer"
    # heroes_wr = heroes_wr.tolist()

    # winrate_data = {
    #     hero: {
    #         "Crusader-": float(attrib[3]) / 100,
    #         "Archon": float(attrib[5]) / 100,
    #         "Legend": float(attrib[7]) / 100,
    #         "Ancient": float(attrib[9]) / 100,
    #         "Divine+": float(attrib[11]) / 100
    #     }
    #     for hero, attrib in zip(heroes_wr, attribs)
    # }

    # for hero, winrate in zip(heroes_wr, winrates):
    #     winrate_data[hero]["All"] = winrate

    return winrate_data

def get_counters_from_dotabuff(driver):
    heroes_disadvantage = {}
    heroes_matchup_winrates = {}
    for hero in heroes:
        logging.info(f"Fetching {hero} data")
        hero_url = hero.lower().replace(' ', '-')
        if hero == "Outworld Devourer":
            hero_url = "outworld-destroyer"
        elif hero == "Nature's Prophet":
            hero_url = "natures-prophet"
        url = f"https://www.dotabuff.com/heroes/{hero_url}/counters"
        success = False
        while not success:
            try:
                # tree = get_page_from_dotabuff(driver, url)
                tree = get_page_from_stratz(driver, url)
                success = True
            except:
                pass
        logging.info("Computing data...")
        divs = tree.xpath("//table[@class='sortable']//tbody//tr//td")
        attribs = [div.attrib["data-value"] for div in divs]
        attribs = np.reshape(attribs, (-1, 5))
        hero_counters = attribs[:, 0]
        if hero != "Outworld Devourer":
            hero_counters[np.where(hero_counters == "Outworld Destroyer")[0][0]] = "Outworld Devourer"
        hero_counters = hero_counters.tolist()
        disadvantages = attribs[:, 2].astype(float)
        matchup_winrates = attribs[:, 3].astype(float)
        disadvantages = disadvantages.tolist()
        heroes_disadvantage[hero] = {
            hero_counter: float(disadvantage)
            for hero_counter, disadvantage in zip(hero_counters, disadvantages)
        }

        heroes_matchup_winrates[hero] = {
            hero_counter: float(matchup_winrate)
            for hero_counter, matchup_winrate in zip(hero_counters, matchup_winrates)
        }
    return heroes_disadvantage, heroes_matchup_winrates

def get_data_from_dotabuff():
    options = Options()
    # options.add_argument("--headless") # disabled has wad making the scraping not working
    options.add_argument("--disable-gpu")
    options.add_argument("--no-sandbox")
    options.add_argument("enable-automation")
    options.add_argument("--disable-infobars")
    options.add_argument("--disable-dev-shm-usage")
    options.add_argument("start-maximized")

    # Chrome is controlled by automated test software
    options.add_experimental_option("excludeSwitches", ["enable-automation"])
    options.add_experimental_option('useAutomationExtension', False)

    logging.info("Installing Google Chrome driver...")
    driver = webdriver.Chrome(ChromeDriverManager().install(), options=options)
    driver.implicitly_wait(10)
    logging.info("Driver installed.")


    winrate_data = get_winrate_data(driver)
    with open("heroes_winrate.yaml", "w") as file:
        yaml.dump(winrate_data, file)

    heroes_disadvantage, heroes_matchup_winrates = get_counters_from_dotabuff(driver)

    data = {
        hero: {
            "winrate": winrate_data[hero],
            "matchup_disadvantage": heroes_disadvantage[hero],
            "matchup_winrate": heroes_matchup_winrates[hero]
        }
        for hero in heroes
    }

    return data

def collect_today_disadvantages(file_name):
    # data = get_data_from_dotabuff()
    data = get_data_from_stratz()


    with open(f"{file_name}.yaml", "w") as file:
        yaml.dump(data, file)

xem_list = ["Chaos Knight", "Luna", "Spectre", "Muerta", "Lifestealer", "Phantom Lancer", "Faceless Void", "Ursa", "Riki", "Wraith King", "Drow Ranger", "Slark", "Gyrocopter", "Bristleback", "Weaver", "Morphling", "Phantom Assassin", "Lycan"]

 

def suggest_hero(p1=None, p2=None, p3=None, p4=None, p5=None, method="mean", filter_list=heroes):
    with open("heroes_disadvantage.yaml", "r") as file:
        all_data = yaml.load(file, Loader=yaml.FullLoader)

    with open("heroes_winrate.yaml", "r") as file:
        winrates = yaml.load(file, Loader=yaml.FullLoader)

    
    
    data = {
        hero: all_data[hero]
        for hero in [p1, p2, p3, p4, p5]
        if hero is not None
    }

    df = pd.DataFrame.from_dict(data)


    df = df * 100
    nb_known_heroes = 5-len(df.columns)
    unknwon_advantage = [(winrates[hero]-0.5)*100 for hero in heroes]
    # for i in range(nb_known_heroes):
    #     df[f"Unknown_{i}"] = pd.Series(unknwon_advantage, index=heroes)

    df = df.loc[filter_list]
    


    df["max"] = df.max(axis=1)
    df["min"] = df.min(axis=1)
    df["mean"] = df.mean(axis=1)
    df = df.sort_values("mean", ascending=False)
    
    pd.set_option('display.max_columns', None)
    pd.set_option('display.width', 1000)
    print(df)



def suggest_hero2(p1=None, p2=None, p3=None, p4=None, p5=None, method="mean", filter_list=heroes):
    with open("simple_draft/dotabuff_data.yaml", "r") as file:
        data = yaml.load(file, Loader=yaml.FullLoader)

    enemy_team = [p1,p2,p3,p4,p5] 
    filter_list = [hero for hero in filter_list if hero not in enemy_team]

    winrates = {
        hero:hero_data["winrate"] for hero, hero_data in data.items()    
    }
    matchup_winrates = {
        hero:hero_data["matchup_winrate"] for hero, hero_data in data.items()
        if hero in filter_list
    }   

    suggestion_data = {
       enemy_hero:  {

            suggested_hero: matchup_winrates[suggested_hero][enemy_hero] if enemy_hero is not None else winrates[suggested_hero] * 100
            for suggested_hero in filter_list
            if enemy_hero != suggested_hero
             
        }
        for enemy_hero in enemy_team
          
    }

    df = pd.DataFrame.from_dict(suggestion_data)
    df["max"] = df.max(axis=1)
    df["min"] = df.min(axis=1)
    df["mean"] = df.mean(axis=1)
    df["adv"] = df["mean"] - np.array([winrates[hero]*100 for hero in filter_list  ])
    df = df.sort_values("adv", ascending=False)
    
    pd.set_option('display.max_columns', None)
    pd.set_option('display.width', 1000)
    print(df)
    pass


nickname_table = {
    "WD":'Witch Doctor', 
    "CK":'Chaos Knight', 
    "WK": 'Wraith King', 
    "Necro": 'Necrophos', 
    "SK": 'Sand King', 
    "LD": 'Lone Druid', 
    "Treant": 'Treant Protector',
    "PL": 'Phantom Lancer', 
    "SB": 'Spirit Breaker', 
    "OD":'Outworld Devourer', 
    "AA": 'Ancient Apparition',
    "SS": 'Shadow Shaman',
    "Ogre": 'Ogre Magi',
    "Centaur": 'Centaur Warrunner', 
    "Nyx": 'Nyx Assassin', 
    "Troll": 'Troll Warlord', 
    "Veno": 'Venomancer', 
    "UD": 'Undying',
    "Naga": 'Naga Siren', 
    "NS": 'Night Stalker', 
    "Venge": 'Vengeful Spirit',
    "AM": 'Anti-Mage', 
    "LS": 'Lifestealer', 
    "Grim": 'Grimstroke', 
    "LC": 'Legion Commander',
    "BB": 'Bristleback', 
    "Sky": 'Skywrath Mage', 
    "ET": 'Elder Titan', 
    "SF": 'Shadow Fiend',
    "BH": 'Bounty Hunter', 
    "NP": "Nature's Prophet", 
    "CM": 'Crystal Maiden',
    "Omni": 'Omniknight', 
    "ES": 'Earthshaker',
    "Drow": 'Drow Ranger', 
    "BS": 'Bloodseeker', 
    "DS": 'Dark Seer', 
    "PB": 'Primal Beast',
    "QoP": 'Queen of Pain', 
    "Brew": 'Brewmaster', 
    "Jugg": 'Juggernaut', 
    "DB": 'Dawnbreaker', 
    "FV": 'Faceless Void',
    "WW": 'Winter Wyvern', 
    "Willow": "Dark Willow",
    "Clock": 'Clockwerk', 
    "PA":'Phantom Assassin', 
    "DK": 'Dragon Knight',
    "DP": 'Death Prophet', 
    "Tide": 'Tidehunter', 
    "Gyro": 'Gyrocopter',
    "Wind": 'Windranger', 
    "TA": 'Templar Assassin', 
    "Lesh": 'Leshrac', 
    "SD": 'Shadow Demon', 
    "Morph": 'Morphling', 
    "MK": 'Monkey King', 
    "KOTL": 'Keeper of the Light', 
    "Snap": "Snapfire",
    "Brood": 'Broodmother', 
    "BM":'Beastmaster', 
    "Timber": 'Timbersaw', 
    "Ench":'Enchantress',
    "Pango": 'Pangolier',
    "TB": 'Terrorblade', 
    "Bat": 'Batrider'
}



if __name__ == "__main__":
    collect_today_disadvantages(file_name="dotabuff_data_7-36a_stratz_1-06_divine")
    # suggest_hero(p1="Anti-Mage", p2=None, p3="Dawnbreaker", p4="Mirana", p5="Witch Doctor", filter_list=xem_list)
    # suggest_hero(p1="Chaos Knight", p2="Necrophos", p3=None, p4="Pudge", p5="Grimstroke", filter_list=xem_list)
    
    # game_heroes = "Necro,Dazzle,LS,Invoker"
    # game_heroes = game_heroes.split(",")
    # game_heroes = [nickname_table.get(hero, hero) for hero in game_heroes]
    # if game_heroes == [""] or game_heroes is None:
    #     game_heroes = [None]
    # suggest_hero2(*game_heroes, filter_list=xem_list)
    
    # with open("simple_draft/dotabuff_data.yaml", "r") as file:
    #     data = yaml.load(file, Loader=yaml.FullLoader)

    # print(data)