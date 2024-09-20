import streamlit as st
 
st.set_page_config(layout="wide")

import yaml
import pandas as pd
import numpy as np
from get_data_from_stratz import get_data_from_stratz, HEROES
from st_files_connection import FilesConnection
import asyncio
import datetime

@st.cache_data
def get_data(data_file):
    with open("heroes.yaml", "r") as file:
        heroes_data = yaml.load(file, Loader=yaml.FullLoader)

    heroes = list(heroes_data.keys())


    def pos_heroes_list(pos):
        return [
            hero
            for hero, hero_data in heroes_data.items()
            if pos in hero_data["roles"]
        ]
    
    p1_list = pos_heroes_list("p1")
    p2_list = pos_heroes_list("p2")
    p3_list = pos_heroes_list("p3")
    p4_list = pos_heroes_list("p4")
    p5_list = pos_heroes_list("p5")


    with open("user_heroes.yaml", "r") as file:
        user_heroes = yaml.load(file, Loader=yaml.FullLoader)

    winrate_data = conn.read(data_file, input_format="text", ttl=600)
    winrate_data = yaml.safe_load(winrate_data)


    nickname_table = {}
    for hero, hero_data in heroes_data.items():
        for nickname in hero_data["nicknames"]:
            nickname_table[nickname] = hero

    return winrate_data, heroes, p1_list, p2_list, p3_list, p4_list, p5_list, user_heroes, nickname_table

conn = st.connection('gcs', type=FilesConnection)

update_data_button = st.sidebar.button("Update Data")
if update_data_button:
    st.sidebar.info("Fetching new data...")
    data = asyncio.run(get_data_from_stratz())
    nb_fetched_heroes = len(data.keys())
    success = nb_fetched_heroes == len(HEROES)

    if success:
        yaml_str = yaml.dump(data)
        date = str(datetime.datetime.now().date())
        file_path = f'heroes-ezdraft/{date}.yaml'
        
        try:
            with conn.fs.open(file_path, 'w') as f:
                f.write(yaml_str)
            st.sidebar.success("New data collected!")
        except Exception as e:
            st.sidebar.error(f"An error occurred: {e}")
    else:
        st.sidebar.error(f"Failed fetching new data, only {nb_fetched_heroes} heroes collected. Try again in 1 minute.")

data_file_list = conn.fs.ls("heroes-ezdraft")
data_file_list = sorted(data_file_list, reverse=True)

data_file_select = st.sidebar.selectbox(
    "Select data",
    data_file_list,
    index=0
)
if data_file_select == "latest":
    data_file = data_file_list[-1]
else:
    data_file = data_file_select
    
st.sidebar.info(f"Using {data_file.split('/')[1][:-5]} data.")

st.title('Dota2 - EZDraft')

winrate_data, heroes, p1_list, p2_list, p3_list, p4_list, p5_list, user_heroes, nickname_table = get_data(data_file)

heroes_str = st.text_input( "Heroes (separated by commas)")
heroes_str = heroes_str.lower()

use_synergy = st.toggle("Synergy", value=False)

filter_list_str = st.selectbox(
    "Select filter list",
    [
        "all heroes",
        "p1",
        "p2",
        "p3",
        "p4",
        "p5",
        *user_heroes.keys()
    ]
)

filter_list = {
    "all heroes": heroes,
    "p1": p1_list,
    "p2": p2_list,
    "p3": p3_list,
    "p4": p4_list,
    "p5": p5_list,
    **user_heroes
}.get(filter_list_str)


def suggest_hero(data, p1=None, p2=None, p3=None, p4=None, p5=None, use_synergy=False, filter_list=heroes):
    enemy_team = [p1,p2,p3,p4,p5] 
    enemy_team = [hero if hero is not None else f"Unknown_{i}" for i, hero in enumerate(enemy_team)]
    filter_list = [hero for hero in filter_list if hero not in enemy_team]

    matchup_or_synergy = "synergy" if use_synergy else "matchup"
    winrate_col = f"{matchup_or_synergy}_winrate"
    disadvantage_col = f"{matchup_or_synergy}_disadvantage"

    winrates = {
        hero:hero_data["winrate"] for hero, hero_data in data.items()    
    }
    matchup_winrates = {
        hero:hero_data["matchup_winrate"] for hero, hero_data in data.items()
        if hero in filter_list
    }   

    suggestion_data = {
       enemy_hero:  {

            suggested_hero: matchup_winrates[suggested_hero][enemy_hero] * 100 if "Unknown" not in enemy_hero else winrates[suggested_hero] * 100
            for suggested_hero in filter_list
            if enemy_hero != suggested_hero
             
        }
        for enemy_hero in enemy_team
          
    }

    df = pd.DataFrame.from_dict(suggestion_data)
    df[winrate_col] = df.mean(axis=1)
    df["max"] = df.max(axis=1)
    df["min"] = df.min(axis=1)
    df["global_winrate"] = np.array([winrates[hero]*100 for hero in filter_list  ])

    heroes_adv = []
    synergy_multiplier = 1 if use_synergy else -1
    for hero in enemy_team:
        if "Unknown" not in hero:
            hero_adv = [synergy_multiplier * data[hero][disadvantage_col][suggested_hero]   for suggested_hero in df.index]
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
    df["meta_condition"] = df[winrate_col] >= 50.0
    df["good_matchups_condition"] = df["advantage"] >= 0.0
    df["score"] =  df["positive_counter_count_condition"].astype(int) + df["meta_condition"].astype(int) + df["good_matchups_condition"].astype(int)

    df = df.sort_values(["score",winrate_col], ascending=False)

    pd.set_option('display.max_columns', None)
    pd.set_option('display.width', 1000)
    
    df = df.loc[:,[
        "score",
        "advantage",
        winrate_col,
        "counter_count",
        "global_winrate",
        *matchup_adv_cols
    ]]
    
    columns = df.columns
    columns = [col for col in columns if "Unknown" not in col]
    df = df.loc[:, columns]

    
    exclude_columns = ["score", "counter_count"]
    df_formatted = df[df.columns.difference(exclude_columns)]
    df_final = pd.concat([df[exclude_columns], df_formatted], axis=1)

    df = df_final.reindex(columns=columns)

    df = df.rename(columns={
        hero_col: hero_col.split("_")[0]
        for hero_col in matchup_adv_cols
    })

    def hero_color_coding(row):
        if row["score"] == 3.0:   
            return ['background-color:#029E73'] * len(row)
        elif row["score"] == 2.0:
            return ['background-color:#DE8F05'] * len(row)
        elif row["score"] == 1.0:
            return ['background-color:#D53801'] * len(row)
        else:
            return ['background-color:black'] * len(row)
        
    df = df.style.apply(hero_color_coding, axis=1).format(
        subset=df.columns.difference(["score", "counter_count"]),
        formatter="{:.2f}"
    )

    st.dataframe(
        df, 
        height=1000,
    )

game_heroes = heroes_str.split(",")
game_heroes = [nickname_table.get(hero, hero) for hero in game_heroes]
if game_heroes == [""] or game_heroes is None:
    game_heroes = [None]
suggest_hero(winrate_data, *game_heroes, use_synergy=use_synergy, filter_list=filter_list )

#TODO
# - recollect new data from button
# - be able to select which dataset to use
# - add hero photos