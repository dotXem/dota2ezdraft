import streamlit as st

st.set_page_config(layout="wide", page_title="EZDraft - Dota 2", page_icon="⚔️")

import yaml
import pandas as pd
import numpy as np
from get_data_from_stratz import HEROES, BRACKETS
from st_files_connection import FilesConnection
from hero_suggestion import *
import streamlit_authenticator as stauth
from user_manager import load_config, save_config, get_user_heroes, register_user, change_password, save_hero_list, delete_hero_list

st.sidebar.header("User")

if "user_config" not in st.session_state:
    st.session_state.user_config = load_config()

config = st.session_state.user_config
username = None
authentication_status = None

authenticator = stauth.Authenticate(
    config['credentials'],
    config['cookie']['name'],
    config['cookie']['key'],
    config['cookie']['expiry_days']
)

name, authentication_status, username = authenticator.login('sidebar')

if authentication_status:
    st.sidebar.write(f'Connected as *{name}*')
    authenticator.logout("Logout", 'sidebar')
    with st.sidebar.expander("Change password"):
        current_pw = st.text_input("Current password", type="password", key="current_pw")
        new_pw = st.text_input("New password", type="password", key="new_pw")
        new_pw_confirm = st.text_input("Confirm new password", type="password", key="new_pw_confirm")
        if st.button("Update password"):
            if not current_pw or not new_pw:
                st.error("Please fill in all fields.")
            elif new_pw != new_pw_confirm:
                st.error("New passwords don't match.")
            else:
                success, err = change_password(config, username, current_pw, new_pw)
                if success:
                    st.success("Password updated!")
                else:
                    st.error(err)
elif authentication_status == False:
    st.sidebar.error('Username/password is incorrect')
elif authentication_status is None:
    st.sidebar.warning('Enter your username and password')

if not authentication_status:
    with st.sidebar.expander("Create an account"):
        reg_name = st.text_input("Display name", key="reg_name")
        reg_username = st.text_input("Username", key="reg_username")
        reg_password = st.text_input("Password", type="password", key="reg_password")
        reg_password_confirm = st.text_input("Confirm password", type="password", key="reg_password_confirm")
        if st.button("Register"):
            if not reg_name or not reg_username or not reg_password:
                st.error("All fields are required.")
            elif len(reg_password) < 8:
                st.error("Password must be at least 8 characters.")
            elif reg_password != reg_password_confirm:
                st.error("Passwords don't match.")
            else:
                success, err = register_user(config, reg_username, reg_name, reg_password)
                if success:
                    st.success("Account created! You can now log in.")
                else:
                    st.error(err)

user_heroes = get_user_heroes(config, username)

st.sidebar.header("Data")

@st.cache_data
def get_data(data_file):
    with open("heroes.yaml", "r") as file:
        heroes_data = yaml.load(file, Loader=yaml.FullLoader)

    heroes = list(heroes_data.keys())

    nickname_table = {}
    for hero, hero_data in heroes_data.items():
        for nickname in hero_data["nicknames"]:
            nickname_table[nickname] = hero

    stratz_data = conn.read(data_file, input_format="text", ttl=600)
    stratz_data = yaml.safe_load(stratz_data)

    winrates_series, enemy_winrates_df, ally_winrates_df = create_winrate_enemy_synergy_dfs(stratz_data)
    counter_scores_df = compute_counter_scores(winrates_series, enemy_winrates_df)
    synergy_scores_df = compute_synergy_scores(winrates_series, ally_winrates_df)
    exceptionnal_counters_df = identify_exceptional_interactions(counter_scores_df, lower_quantile=0.10, upper_quantile=0.90)
    exceptionnal_synergy_df = identify_exceptional_interactions(synergy_scores_df, lower_quantile=0.10, upper_quantile=0.90)

    heroes_per_position = {
        f"POSITION_{i}": []
        for i in range(1, 6)
    }
    for hero, hero_data in stratz_data.items():
        for position in hero_data["positions"]:
            heroes_per_position[position].append(hero)

    winrates_per_bracket = {
        bracket: {}
        for bracket in stratz_data["Lion"]["winrate_brackets"].keys()
    }
    for hero_name, hero_data in stratz_data.items():
        for bracket, winrate in hero_data["winrate_brackets"].items():
            winrates_per_bracket[bracket][hero_name] = winrate
    winrates_per_bracket = {
        bracket: pd.Series(winrates)
        for bracket, winrates in winrates_per_bracket.items()
    }

    return winrates_per_bracket, counter_scores_df, synergy_scores_df, exceptionnal_counters_df, exceptionnal_synergy_df, heroes, *heroes_per_position.values(), nickname_table

conn = st.connection('gcs', type=FilesConnection)

data_file_list = conn.fs.ls("heroes-ezdraft/data/")
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
    
st.sidebar.info(f"Using {data_file.split('/')[2][:-5]} data.")

(
    winrates_per_bracket, 
    counter_scores_df, 
    synergy_scores_df, 
    exceptionnal_counters_df, 
    exceptionnal_synergy_df, 
    heroes, 
    p1_list, p2_list, p3_list, p4_list, p5_list, 
    nickname_table 
) = get_data(data_file)

bracketst_str = [
    "[" + ",".join(bracket) + "]"
    for bracket in BRACKETS
]

bracket = st.sidebar.selectbox(
    "Select bracket data",
    bracketst_str,
)

st.title('Dota2 - EZDraft')

def display_hero_suggestions(winrates_series, counter_scores_df, synergy_scores_df, enemy_heroes, ally_heroes, filter_list=heroes):
    suggestions_df = suggest_heroes_from_ally_and_enemy(
        winrates_series, 
        counter_scores_df, 
        synergy_scores_df, 
        exceptionnal_counters_df, 
        exceptionnal_synergy_df,
        enemy_heroes, 
        ally_heroes,
    )
    
    filter_list = [hero for hero in filter_list if hero not in enemy_heroes + ally_heroes]
    suggestions_df = suggestions_df.loc[filter_list]
    suggestions_df = suggestions_df.sort_values(["relevance", "score"], ascending=False)
    
    pd.set_option('display.max_columns', None)
    pd.set_option('display.width', 1000)
    
    suggestions_df = suggestions_df.loc[:,[
        "relevance",
        "score",
        "winrate",
        "impact",
        "score_enemy",
        *enemy_heroes,
        "score_ally",
        *ally_heroes
    ]]

    all_winrate_columns = suggestions_df.columns.difference(["relevance", "impact"])
    suggestions_df.loc[:, all_winrate_columns] = suggestions_df.loc[:, all_winrate_columns] * 100
    
    def hero_color_coding(row):
        if row["relevance"] == 3.0:   
            return ['background-color:#029E73'] * len(row)
        elif row["relevance"] == 2.0:
            return ['background-color:#DE8F05'] * len(row)
        elif row["relevance"] == 1.0:
            return ['background-color:#D53801'] * len(row)
        else:
            return ['background-color:black'] * len(row)
        
    suggestions_df = suggestions_df.style.apply(hero_color_coding, axis=1).format(
        subset=all_winrate_columns,
        formatter="{:.2f}"
    )

    st.dataframe(
        suggestions_df, 
        height=1000,
    )

draft_tab, lists_tab = st.tabs(["Draft", "My Hero Lists"])

with draft_tab:
    # Initialize session state for the input fields if not already present
    if "enemy_heroes" not in st.session_state:
        st.session_state.enemy_heroes = ""
    if "ally_heroes" not in st.session_state:
        st.session_state.ally_heroes = ""

    # Swap teams button
    if st.button("Swap Teams"):
        st.session_state.enemy_heroes, st.session_state.ally_heroes = st.session_state.ally_heroes, st.session_state.enemy_heroes

    # Input fields using session state values
    enemy_heroes_str = st.text_input("Enemy heroes (separated by commas)", value=st.session_state.enemy_heroes, key="enemy_heroes")
    ally_heroes_str = st.text_input("Ally heroes (separated by commas)", value=st.session_state.ally_heroes, key="ally_heroes")

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

    enemy_heroes = enemy_heroes_str.split(",")
    enemy_heroes = [nickname_table.get(hero, hero) for hero in enemy_heroes]
    if enemy_heroes == [""] or enemy_heroes is None:
        enemy_heroes = []

    ally_heroes = ally_heroes_str.split(",")
    ally_heroes = [nickname_table.get(hero, hero) for hero in ally_heroes]
    if ally_heroes == [""] or ally_heroes is None:
        ally_heroes = []

    display_hero_suggestions(winrates_per_bracket[bracket], counter_scores_df, synergy_scores_df, enemy_heroes, ally_heroes, filter_list=filter_list)

with lists_tab:
    if not authentication_status:
        st.info("Log in to manage your custom hero lists.")
    else:
        with st.form("create_list_form"):
            st.subheader("Create a new list")
            new_list_name = st.text_input("List name")
            new_list_heroes = st.multiselect("Select heroes", sorted(heroes))
            submitted = st.form_submit_button("Create list")
            if submitted:
                if not new_list_name:
                    st.error("Please enter a list name.")
                elif not new_list_heroes:
                    st.error("Please select at least one hero.")
                else:
                    save_hero_list(config, username, new_list_name, new_list_heroes)
                    st.success(f"List '{new_list_name}' created!")
                    st.rerun()

        if user_heroes:
            st.subheader("Your lists")
            for list_name, hero_list in user_heroes.items():
                with st.expander(f"{list_name} ({len(hero_list)} heroes)"):
                    updated = st.multiselect(
                        "Heroes",
                        sorted(heroes),
                        default=hero_list,
                        key=f"edit_{list_name}"
                    )
                    col1, col2 = st.columns(2)
                    with col1:
                        if st.button("Save", key=f"save_{list_name}"):
                            save_hero_list(config, username, list_name, updated)
                            st.success("Saved!")
                            st.rerun()
                    with col2:
                        if st.button("Delete", key=f"del_{list_name}"):
                            delete_hero_list(config, username, list_name)
                            st.success("Deleted!")
                            st.rerun()
        else:
            st.info("No custom lists yet. Create one above!")
