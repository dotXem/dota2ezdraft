import streamlit as st

st.set_page_config(layout="wide", page_title="EZDraft - Dota 2", page_icon="⚔️")

import yaml
import pandas as pd
import numpy as np
from get_data_from_stratz import HEROES, BRACKETS
from st_files_connection import FilesConnection
from hero_suggestion import *
import streamlit_authenticator as stauth
from user_manager import load_config, save_config, get_user_heroes, register_user, change_password, save_hero_list, delete_hero_list, is_scouting_user, get_scouting_teams, save_scouting_team, delete_scouting_team
from scouting_api import fetch_all_scouting_data, normalize_steam_id, generate_player_image, generate_team_games_image, generate_full_scouting_image, get_hero_icon_url
from pro_meta_api import fetch_recent_leagues, fetch_pro_meta, draft_to_html, lookup_league_info

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

    # Add hero icon column
    suggestions_df.insert(0, "Icon", suggestions_df.index.map(lambda h: get_hero_icon_url(h) or ""))

    all_winrate_columns = suggestions_df.columns.difference(["relevance", "impact", "Icon"])
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
        column_config={
            "Icon": st.column_config.ImageColumn("", width="small"),
        },
    )

show_scouting = authentication_status and is_scouting_user(config, username)
tab_names = ["Draft", "My Hero Lists", "Pro Meta"]
if show_scouting:
    tab_names.append("Scouting")
tab_objects = st.tabs(tab_names)
draft_tab = tab_objects[0]
lists_tab = tab_objects[1]
meta_tab = tab_objects[2]

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

with meta_tab:
    st.subheader("Pro Meta — Tournament Hero Stats")

    # Fetch league list (cached in session state)
    if "pro_meta_leagues" not in st.session_state:
        st.session_state.pro_meta_leagues = None

    if st.button("Load recent tournaments", key="meta_load_leagues"):
        with st.spinner("Fetching tournament list from OpenDota..."):
            try:
                st.session_state.pro_meta_leagues = fetch_recent_leagues(count=20)
            except Exception as e:
                st.error(f"Error fetching leagues: {e}")

    leagues = st.session_state.pro_meta_leagues

    # --- League selection: dropdown or manual ID ---
    selected_league_id = None
    col_sel, col_manual = st.columns([3, 1])
    with col_sel:
        if leagues:
            league_options = {
                f"{l['name']} — {l['match_count']} games ({l['last_match']})": l["id"]
                for l in leagues
            }
            selected_league_label = st.selectbox(
                "Select tournament", list(league_options.keys()), key="meta_league_sel"
            )
            selected_league_id = league_options[selected_league_label]
        else:
            st.info("Click **Load recent tournaments** to populate the list, or enter a League ID manually.")

    with col_manual:
        manual_id = st.text_input("Or enter League ID", key="meta_manual_id", placeholder="e.g. 19269")
        if manual_id.strip():
            try:
                selected_league_id = int(manual_id.strip())
            except ValueError:
                st.error("Invalid ID")

    if selected_league_id:
        meta_key = f"pro_meta_data_{selected_league_id}"

        if meta_key in st.session_state:
            fetched_at = st.session_state[meta_key].get("fetched_at", "")
            if fetched_at:
                import datetime as _dt
                try:
                    ft = _dt.datetime.fromisoformat(fetched_at)
                    delta = _dt.datetime.utcnow() - ft
                    hours = delta.total_seconds() / 3600
                    if hours < 1:
                        age_str = f"{int(delta.total_seconds() / 60)} minutes ago"
                    else:
                        age_str = f"{hours:.1f} hours ago"
                    st.caption(f"📦 Data cached — last fetched {age_str}")
                except ValueError:
                    pass

        if st.button("Fetch tournament data", type="primary", key="meta_fetch_btn"):
            # Look up league name for display (especially for manual IDs)
            league_info = lookup_league_info(selected_league_id)
            league_name = league_info.get("name", f"League {selected_league_id}")

            with st.spinner(f"Fetching {league_name} matches..."):
                try:
                    result = fetch_pro_meta(selected_league_id)
                    st.session_state[meta_key] = result
                    st.success(f"Fetched {result['total_matches']} matches for {league_name}!")
                except Exception as e:
                    st.error(f"Error: {e}")

        if meta_key in st.session_state:
            meta_data = st.session_state[meta_key]
            hero_stats = meta_data["hero_stats"]
            drafts = meta_data["drafts"]
            total_matches = meta_data["total_matches"]

            st.markdown(f"**{total_matches} matches** in this tournament")
            st.markdown("---")

            # --- Hero Contest Stats ---
            st.subheader("Hero Contest Stats")
            if not hero_stats.empty:
                display_stats = hero_stats
                # Hide Pos columns when position data is unavailable (all zeros)
                pos_cols = [c for c in display_stats.columns if c.startswith("Pos ")]
                if pos_cols and display_stats[pos_cols].sum().sum() == 0:
                    display_stats = display_stats.drop(columns=pos_cols)
                st.dataframe(
                    display_stats,
                    column_config={
                        "Icon": st.column_config.ImageColumn("", width="small"),
                        "Winrate": st.column_config.NumberColumn(format="%.1f%%"),
                        "Pick%": st.column_config.NumberColumn(format="%.1f%%"),
                        "Ban%": st.column_config.NumberColumn(format="%.1f%%"),
                        "Contest%": st.column_config.NumberColumn(format="%.1f%%"),
                    },
                    hide_index=True,
                    use_container_width=True,
                    height=800,
                )
            else:
                st.info("No hero data available.")

            st.markdown("---")

            # --- Recent Drafts ---
            st.subheader(f"Recent Drafts (last {len(drafts)} games)")
            for draft in drafts:
                winner_label = "🏆 " + draft["winner"]
                label = f"{draft['radiant']} vs {draft['dire']} — {winner_label} — {draft['date']}"
                with st.expander(label):
                    html = draft_to_html(draft)
                    st.html(html)

if show_scouting:
    with tab_objects[3]:
        teams = get_scouting_teams(config, username)

        # --- Create Team ---
        with st.expander("Create a new team"):
            new_team_name = st.text_input("Team name", key="scout_new_name")
            new_team_ids = st.text_area(
                "Player Steam IDs (one per line, 32-bit or 64-bit)",
                placeholder="e.g.\n12345678\n87654321",
                key="scout_new_ids",
                height=150,
            )
            if st.button("Create team", key="scout_create_btn"):
                if not new_team_name.strip():
                    st.error("Enter a team name.")
                elif not new_team_ids.strip():
                    st.error("Enter at least one Steam ID.")
                else:
                    try:
                        players = []
                        for line in new_team_ids.strip().splitlines():
                            line = line.strip()
                            if line:
                                sid = normalize_steam_id(line)
                                players.append({"steam_id": sid, "name": ""})
                        if not players:
                            st.error("No valid Steam IDs entered.")
                        else:
                            save_scouting_team(config, username, new_team_name.strip(), players)
                            st.success(f"Team '{new_team_name.strip()}' created with {len(players)} players!")
                            st.rerun()
                    except ValueError:
                        st.error("Invalid Steam ID. Use numeric 32-bit or 64-bit IDs.")

        # --- Team Selection & Scouting ---
        if not teams:
            st.info("No scouting teams yet. Create one above!")
        else:
            selected_team = st.selectbox("Select team", list(teams.keys()), key="scout_team_sel")
            team_data = teams[selected_team]
            players = team_data.get("players", [])

            # Show current roster
            if players:
                player_display = ", ".join(p.get("name") or str(p["steam_id"]) for p in players)
                st.caption(f"Roster: {player_display}")

            # Edit team
            with st.expander("Edit team"):
                edit_ids = st.text_area(
                    "Steam IDs (one per line)",
                    value="\n".join(str(p["steam_id"]) for p in players),
                    key="scout_edit_ids",
                )
                ecol1, ecol2 = st.columns(2)
                with ecol1:
                    if st.button("Save changes", key="scout_save_btn"):
                        try:
                            updated = []
                            existing = {p["steam_id"]: p.get("name", "") for p in players}
                            for line in edit_ids.strip().splitlines():
                                line = line.strip()
                                if line:
                                    sid = normalize_steam_id(line)
                                    updated.append({"steam_id": sid, "name": existing.get(sid, "")})
                            save_scouting_team(config, username, selected_team, updated)
                            st.success("Team updated!")
                            st.rerun()
                        except ValueError:
                            st.error("Invalid Steam ID format.")
                with ecol2:
                    if st.button("Delete team", key="scout_del_btn"):
                        delete_scouting_team(config, username, selected_team)
                        st.success(f"Team '{selected_team}' deleted!")
                        st.rerun()

            # Fetch data
            scout_key = f"scout_data_{selected_team}"

            # Show cache status
            if scout_key in st.session_state:
                fetched_at = st.session_state[scout_key].get("fetched_at", "")
                if fetched_at:
                    import datetime as _dt
                    try:
                        ft = _dt.datetime.fromisoformat(fetched_at)
                        delta = _dt.datetime.utcnow() - ft
                        hours = delta.total_seconds() / 3600
                        if hours < 1:
                            age_str = f"{int(delta.total_seconds() / 60)} minutes ago"
                        else:
                            age_str = f"{hours:.1f} hours ago"
                        st.caption(f"📦 Data cached — last fetched {age_str}")
                    except ValueError:
                        pass

            if st.button("Fetch scouting data from Stratz", type="primary", key="scout_fetch_btn"):
                with st.spinner(f"Fetching data for {len(players)} players from Stratz..."):
                    try:
                        result = fetch_all_scouting_data(players)
                        st.session_state[scout_key] = result
                        # Update player names from fetched data
                        for p in players:
                            sid = normalize_steam_id(p["steam_id"])
                            fetched_name = result["player_names"].get(sid, "")
                            if fetched_name:
                                p["name"] = fetched_name
                        save_scouting_team(config, username, selected_team, players)
                        st.success("Data fetched successfully!")
                    except Exception as e:
                        st.error(f"Error fetching data: {e}")

            # Display results
            if scout_key in st.session_state:
                data = st.session_state[scout_key]
                fetched_ts = data.get("fetched_at", "")

                # Full composite image download
                full_img = generate_full_scouting_image(data, selected_team, players)
                if full_img:
                    st.download_button(
                        "🖼️ Download full scouting image",
                        data=full_img,
                        file_name=f"scouting_{selected_team.replace(' ', '_')}_full.png",
                        mime="image/png",
                        key=f"img_full_{fetched_ts}",
                    )

                st.markdown("---")
                st.subheader("Player Hero Pools (Past 2 Months)")

                for p in players:
                    sid = normalize_steam_id(p["steam_id"])
                    name = data["player_names"].get(sid, str(sid))
                    hero_df = data.get("player_heroes", {}).get(sid, pd.DataFrame())

                    dotabuff = f"https://www.dotabuff.com/players/{sid}"
                    stratz_url = f"https://stratz.com/players/{sid}"
                    opendota = f"https://www.opendota.com/players/{sid}"

                    with st.expander(f"**{name}** (ID: {sid})", expanded=True):
                        st.markdown(
                            f"[Dotabuff]({dotabuff}) · [Stratz]({stratz_url}) · [OpenDota]({opendota})"
                        )

                        if hero_df.empty:
                            st.warning("No matches found — profile may be private.")
                        else:
                            st.markdown(f"**Heroes played in the past 2 months ({len(hero_df)} heroes):**")
                            st.dataframe(
                                hero_df,
                                column_config={
                                    "Icon": st.column_config.ImageColumn("", width="small"),
                                    "Winrate": st.column_config.NumberColumn(format="%.1f%%"),
                                },
                                hide_index=True,
                                use_container_width=True,
                            )

                        # Per-player image download
                        player_img = generate_player_image(data, p["steam_id"])
                        if player_img:
                            st.download_button(
                                f"🖼️ Download {name} image",
                                data=player_img,
                                file_name=f"scouting_{name.replace(' ', '_')}.png",
                                mime="image/png",
                                key=f"img_player_{sid}_{fetched_ts}",
                            )

                st.markdown("---")
                st.subheader("Team Games (Past 2 Months)")
                team_games = data.get("team_games", pd.DataFrame())
                if team_games.empty:
                    st.info("No games found where team members played together.")
                else:
                    display_games = team_games.head(15)
                    st.caption(f"Showing {len(display_games)} of {len(team_games)} games with 2+ team members on the same side.")
                    st.dataframe(
                        display_games,
                        hide_index=True,
                        use_container_width=True,
                    )

                    # Team games image download
                    team_img = generate_team_games_image(data, selected_team)
                    if team_img:
                        st.download_button(
                            "🖼️ Download Team Games image",
                            data=team_img,
                            file_name=f"scouting_{selected_team.replace(' ', '_')}_team_games.png",
                            mime="image/png",
                            key=f"img_team_{fetched_ts}",
                        )

                # --- Tournament Drafts (5-player games) ---
                scout_drafts = data.get("drafts", [])
                if scout_drafts:
                    st.markdown("---")
                    st.subheader(f"Tournament Drafts — Full Team ({len(scout_drafts)} games)")
                    for draft in scout_drafts:
                        winner_label = "🏆 " + draft["winner"]
                        label = f"{draft['radiant']} vs {draft['dire']} — {winner_label} — {draft['date']}"
                        with st.expander(label):
                            html = draft_to_html(draft)
                            st.html(html)
