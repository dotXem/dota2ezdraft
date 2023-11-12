import streamlit as st
 
st.set_page_config(layout="wide")

import yaml
import pandas as pd
import numpy as np

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
 
p1_list = ["Spectre", "Faceless Void","Weaver","Luna","Chaos Knight", "Muerta","Morphling", "Lifestealer", "Templar Assassin", "Slark", "Naga Siren", "Wraith King", "Sven", "Phantom Assassin", "Terrorblade", "Phantom Lancer", "Monkey King", "Bristleback", "Ursa", "Bloodseeker", "Troll Warlord", "Anti-Mage","Alchemist", "Lone Druid","Dark Willow", "Drow Ranger", "Gyrocopter", "Juggernaut", "Pudge", "Razor", "Riki", "Magnus","Shadow Fiend", "Sniper","Clinkz","Windranger","Medusa"]
p2_list = ["Kunkka", "Invoker", "Earth Spirit", "Pangolier", "Primal Beast", "Necrophos", "Puck", "Lina", "Queen of Pain", "Dazzle", "Outworld Devourer", "Zeus", "Storm Spirit", "Huskar", "Earthshaker", "Templar Assassin", "Magnus", "Void Spirit", "Keeper of the Light", "Tinker", "Lone Druid", "Ember Spirit", "Shadow Fiend", "Monkey King", "Arc Warden", "Pugna", "Tiny", "Bristleback", "Slardar", "Clinkz", "Windranger", "Leshrac", "Batrider", "Ogre Magi", "Meepo", "Marci", "Razor", "Spirit Breaker", "Sniper", "Viper", "Riki", "Death Prophet", "Visage", "Nyx Assassin", "Pudge", "Timbersaw", "Rubick", "Tusk", "Snapfire", "Dragon Knight"] 
p3_list = ['Chaos Knight', 'Wraith King', 'Slardar', 'Necrophos', 'Sand King', 'Lone Druid', 'Kunkka', 'Abaddon', 'Spirit Breaker', 'Centaur Warrunner', 'Venomancer',  'Axe', 'Night Stalker', 'Visage', 'Viper',  'Legion Commander', 'Bristleback', 'Bounty Hunter', 'Weaver','Omniknight', 'Earthshaker', 'Underlord','Bloodseeker', 'Dark Seer', 'Primal Beast','Brewmaster', 'Pudge','Marci', 'Razor', 'Dragon Knight','Death Prophet', 'Tidehunter', 'Enigma', 'Magnus', 'Tusk',  'Mars',  'Broodmother', 'Doom', 'Beastmaster', 'Tiny', 'Timbersaw', 'Pangolier']
p4_list = ['Witch Doctor', 'Treant Protector', 'Jakiro',
 'Warlock', 'Silencer', 'Abaddon',
 'Spirit Breaker', 'Ancient Apparition',
 'Shadow Shaman', 'Oracle', 'Lich', 'Muerta', 'Ogre Magi',
 'Nyx Assassin', 'Venomancer', 'Undying',
 'Clinkz', 'Vengeful Spirit',
 'Grimstroke', 
 'Sniper', 'Skywrath Mage', 'Elder Titan', 'Io',
 'Bounty Hunter', "Nature's Prophet", 'Weaver', 'Dazzle', 'Crystal Maiden',
 'Omniknight', 'Earthshaker', 'Chen', 'Bane', 'Pugna', 'Invoker', 'Pudge',
 'Dawnbreaker', 'Disruptor', 
 'Hoodwink', 'Marci', 'Winter Wyvern', 'Phoenix', 'Dark Willow',
 'Clockwerk', 'Earth Spirit', 'Mirana',  
 'Windranger', 'Techies', 'Enigma', 'Shadow Demon', 'Lion', 'Magnus',
 'Tusk', 'Monkey King', 'Keeper of the Light', 'Snapfire',
 'Enchantress',
 'Rubick', 'Batrider']
p5_list = p4_list

xem_list = ["Chaos Knight", "Luna", "Spectre", "Muerta", "Lifestealer", "Phantom Lancer", "Faceless Void", "Ursa", "Riki", "Wraith King", "Drow Ranger", "Slark", "Gyrocopter", "Bristleback", "Weaver", "Morphling", "Phantom Assassin"]

GBO_p4_list = ["Queen of Pain", "Zeus", "Invoker", "Spirit Breaker", "Phoenix", "Dazzle", "Undying", "Shadow Shaman", "Pudge", "Gyrocopter", "Clinkz", "Venomancer", "Earthshaker", "Ogre Magi", "Nature's Prophet"]
thunder_p2_list = ["Invoker", "Pangolier", "Outworld Devourer", "Tusk", "Kunkka", "Earthshaker", "Necrophos", "Dazzle", "Spirit Breaker", "Earth Spirit", "Primal Beast", "Puck", "Zeus"]
lunatix_p3_list = ["Brewmaster", "Visage", "Broodmother", "Razor", "Dazzle", "Bristleback", "Primal Beast", "Axe", "Earthshaker"]
exit_p5_list = ["Shadow Shaman", "Witch Doctor", "Lion", "Crystal Maiden", "Treant Protector", "Lich", "Warlock", "Venomancer", "Spirit Breaker", "Vengeful Spirit", "Snapfire", "Dazzle", "Bane", "Jakiro", "Ancient Apparition", "Omniknight", "Earthshaker", "Ogre Magi"]
ice_b_list = xem_list+GBO_p4_list+thunder_p2_list+lunatix_p3_list+exit_p5_list

@st.cache_data
def get_data():
    with open("dotabuff_data.yaml", "r") as file:
        data = yaml.load(file, Loader=yaml.FullLoader)
    return data

def suggest_hero():
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

st.title('Dota2 - EZDraft')
st.set_option('deprecation.showPyplotGlobalUse', False)

heroes_str = st.text_input( "Heroes (separated by commas)")

filter_list_str = st.selectbox(
    "Select filter list",
    [
        "all heroes",
        "p1",
        "p2",
        "p3",
        "p4",
        "p5",
        "Xem's p1",
        "Thunder's p2",
        "Lunatix's p3",
        "GBO's p4",
        "Exit's p5",
        "Icewrack B",
    ]
)
filter_list = {
    "all heroes": heroes,
    "p1": p1_list,
    "p2": p2_list,
    "p3": p3_list,
    "p4": p4_list,
    "p5": p5_list,
    "Xem's p1": xem_list,
    "Thunder's p2": thunder_p2_list,
    "Lunatix's p3": lunatix_p3_list,
    "GBO's p4": GBO_p4_list,
    "Exit's p5": exit_p5_list,
    "Icewrack B": ice_b_list
}.get(filter_list_str)
data = get_data()


def suggest_hero(p1=None, p2=None, p3=None, p4=None, p5=None, method="matchup_winrate", filter_list=heroes):
    with open("dotabuff_data.yaml", "r") as file:
        data = yaml.load(file, Loader=yaml.FullLoader)

    enemy_team = [p1,p2,p3,p4,p5] 
    enemy_team = [hero if hero is not None else f"Unknown_{i}" for i, hero in enumerate(enemy_team)]
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

            suggested_hero: matchup_winrates[suggested_hero][enemy_hero] if "Unknown" not in enemy_hero else winrates[suggested_hero] * 100
            for suggested_hero in filter_list
            if enemy_hero != suggested_hero
             
        }
        for enemy_hero in enemy_team
          
    }

    df = pd.DataFrame.from_dict(suggestion_data)
    df["max"] = df.max(axis=1)
    df["min"] = df.min(axis=1)
    df["matchup_winrate"] = df.mean(axis=1)
    df["global_winrate"] = np.array([winrates[hero]*100 for hero in filter_list  ])

    heroes_adv = []
    for hero in enemy_team:
        if "Unknown" not in hero:
            hero_adv = [data[hero]["matchup_disadvantage"][suggested_hero]   for suggested_hero in df.index]
        else:
            hero_adv = [0.0] * len(df.index)
        heroes_adv.append(hero_adv) 
    matchup_adv_cols = [hero + "_matchup_adv" for hero in enemy_team]
    matchup_df = pd.DataFrame(
        data=np.array(heroes_adv).transpose(),
        columns=matchup_adv_cols,
        index=df.index
    )    

    df = pd.concat([df, matchup_df],axis=1)
    df["advantage"] = df.loc[:, matchup_adv_cols].mean(axis=1)

    df["nb_counters"] = (df.loc[:,matchup_adv_cols] <= -2.21212).sum(axis=1) #len(np.where(np.array(heroes_adv) <=  -2.21212)[0])
    df["nb_countered"] = (df.loc[:,matchup_adv_cols] >= 2.3972399999999987).sum(axis=1)
    df["counter_count"] = df["nb_countered"] - df["nb_counters"] 
    df["positive_counter_count_condition"] = df["counter_count"] >= 0.0
    df["meta_condition"] = df["matchup_winrate"] >= 50.0
    df["good_matchups_condition"] = df["advantage"] >= 0.0

    df["score"] =  df["positive_counter_count_condition"].astype(int) + df["meta_condition"].astype(int) + df["good_matchups_condition"].astype(int)

    df = df.sort_values(["score","matchup_winrate"], ascending=False)
    
    pd.set_option('display.max_columns', None)
    pd.set_option('display.width', 1000)
    
    df = df.loc[:,[
        "score",
        "advantage",
        "matchup_winrate",
        "counter_count",
        "global_winrate",
        *matchup_adv_cols
    ]]

    def hero_color_coding(row):
        if row["score"] == 3.0:   
            return ['background-color:#029E73'] * len(row)
        elif row["score"] == 2.0:
            return ['background-color:#DE8F05'] * len(row)
        elif row["score"] == 1.0:
            return ['background-color:#D53801'] * len(row)
        else:
            return ['background-color:black'] * len(row)
    df = df.style.apply(hero_color_coding, axis=1)

    st.dataframe(
        df, 
        use_container_width=True, height=1000
    )


game_heroes = heroes_str.split(",")
game_heroes = [nickname_table.get(hero, hero) for hero in game_heroes]
if game_heroes == [""] or game_heroes is None:
    game_heroes = [None]
suggest_hero(*game_heroes, filter_list=filter_list )
