import numpy as np
import pandas as pd

def suggest_heroes_from_ally_and_enemy(
    winrates_series, 
    counter_scores_df, 
    synergy_scores_df, 
    exceptionnal_counters_df, 
    exceptionnal_synergy_df,
    enemy_heroes, 
    ally_heroes
):
    suggestions_df = create_enemy_ally_suggestions_aggregate(winrates_series, counter_scores_df, synergy_scores_df, enemy_heroes, ally_heroes)
    suggestions_df = add_analysis_to_suggestions(suggestions_df, exceptionnal_counters_df, exceptionnal_synergy_df, enemy_heroes, ally_heroes)
    return suggestions_df

def create_enemy_ally_suggestions_aggregate(winrates_series, counter_scores_df, synergy_scores_df, enemy_heroes, ally_heroes):
    enemy_suggestions_df = suggest_heroes(winrates_series, counter_scores_df, enemy_heroes)
    ally_suggestions_df = suggest_heroes(winrates_series, synergy_scores_df, ally_heroes)
    suggestions_df = enemy_suggestions_df.join(ally_suggestions_df, how='left', lsuffix='_enemy', rsuffix='_ally')
    suggestions_df["score"] = suggestions_df["score_enemy"] + suggestions_df["score_ally"]
    suggestions_df["winrate"] = suggestions_df["winrate_enemy"]
    suggestions_df.drop(columns=["winrate_enemy", "winrate_ally"], inplace=True)
    suggestions_df = suggestions_df.loc[:, ["score", "winrate", "score_enemy", *enemy_heroes, "score_ally", *ally_heroes]]
    suggestions_df = suggestions_df.sort_values("score", ascending=False)
    return suggestions_df

def add_analysis_to_suggestions(suggestions_df, exceptionnal_counters_df, exceptionnal_synergy_df, enemy_heroes, ally_heroes):
    suggestions_df["hero_is_meta"] = suggestions_df["winrate"] >= 0.5
    suggestions_df["good_score"] = suggestions_df["score"] >= 0.0

    exceptionnal_interactions_df = pd.concat(
        [
            exceptionnal_counters_df.loc[:, enemy_heroes],
            exceptionnal_synergy_df.loc[:, ally_heroes]
        ], axis=1
    )
    exceptionnal_interactions_counts = exceptionnal_interactions_df.sum(axis=1)
    suggestions_df["impact"] = exceptionnal_interactions_counts

    suggestions_df["relevance"] = (
        suggestions_df["hero_is_meta"].astype(int) +
        suggestions_df["good_score"].astype(int) +
        (suggestions_df["impact"] >= 0).astype(int)
    )
    return suggestions_df

def suggest_heroes(winrates_series, scores_df, selected_heroes):
    heroes_scores_df  = compute_selected_heroes_scores(scores_df, selected_heroes)
    selected_heroes_suggestions_df = create_suggestions_df(winrates_series, scores_df, heroes_scores_df, selected_heroes)    
    return selected_heroes_suggestions_df

def create_winrate_enemy_synergy_dfs(data):
    winrates_series = pd.Series({
        hero:hero_data["winrate"] for hero, hero_data in data.items()    
    })

    enemy_winrates_df = pd.DataFrame.from_dict({
        hero:hero_data["matchup_winrate"] for hero, hero_data in data.items()
    } ).transpose()
    enemy_winrates_df = ((
        1-enemy_winrates_df.transpose().loc[enemy_winrates_df.index, enemy_winrates_df.columns]
    ) + enemy_winrates_df) / 2

    ally_winrates_df = pd.DataFrame.from_dict({
        hero:hero_data["synergy_winrate"] for hero, hero_data in data.items()
    })
    ally_winrates_df = (ally_winrates_df + ally_winrates_df.transpose()) / 2
    return winrates_series, enemy_winrates_df, ally_winrates_df

def create_suggestions_df(winrates_series, scores_df, selected_heroes_scores_df, selected_heroes):
    all_heroes = set(scores_df.index)
    available_heroes = list(all_heroes - set(selected_heroes))
    suggestions_df = pd.DataFrame(index=available_heroes)
    winrates_series = pd.Series(winrates_series)
    suggestions_df["winrate"] = winrates_series.loc[available_heroes]
    suggestions_df = suggestions_df.join(selected_heroes_scores_df, how='left')
    suggestions_df = suggestions_df.join(scores_df.loc[available_heroes, selected_heroes], how='left')
    columns_order = ["score", 'winrate'] + selected_heroes
    suggestions_df = suggestions_df.loc[:, columns_order]
    return suggestions_df

def compute_synergy_scores(winrates, ally_winrates_df):
    """
    Computes the synergy scores for all pairs of heroes.

    Parameters:
    - winrates: dict mapping hero names to their individual win rates (decimals between 0 and 1).
    - pair_winrates_df: pandas DataFrame where rows and columns are hero names,
      and the cell (i, j) is the win rate (between 0 and 1) when heroes i and j play together.

    Returns:
    - synergy_scores_df: pandas DataFrame with synergy scores for all hero pairs.
    """
    # Ensure the DataFrame has the same heroes in rows and columns
    heroes = list(winrates.keys())
    synergy_scores_df = pd.DataFrame(index=heroes, columns=heroes, dtype=float)

    for hero_a in heroes:
        for hero_b in heroes:
            if hero_a == hero_b:
                # Synergy with oneself is not defined; set as NaN or 0
                synergy_scores_df.loc[hero_a, hero_b] = None  # or 0
                continue

            try:
                # Individual win rates
                w_A = winrates[hero_a]
                w_B = winrates[hero_b]

                # Combined win rate when both heroes play together
                w_AB = ally_winrates_df.loc[hero_a, hero_b]

                # Calculate individual contributions relative to 0.5 (50%)
                s_A = w_A - 0.5
                s_B = w_B - 0.5

                # Expected combined win rate
                expected_w_AB = 0.5 + s_A + s_B

                # Synergy score
                synergy_score = w_AB - expected_w_AB

                # Store the synergy score
                synergy_scores_df.loc[hero_a, hero_b] = synergy_score
            except KeyError:
                # Handle missing data
                synergy_scores_df.loc[hero_a, hero_b] = None

    return synergy_scores_df

def compute_counter_scores(winrates_series, enemy_winrates_df):
    """
    Computes the counter scores for all pairs of heroes.

    Parameters:
    - winrates: dict mapping hero names to their individual win rates (decimals between 0 and 1).
    - matchup_winrates_df: pandas DataFrame where rows and columns are hero names,
      and the cell (i, j) is the win rate (between 0 and 1) of Hero i when facing Hero j.

    Returns:
    - counter_scores_df: pandas DataFrame with counter scores for all hero pairs.
    """
    # Ensure the DataFrame has the same heroes in rows and columns
    heroes = list(winrates_series.index)
    counter_scores_df = pd.DataFrame(index=heroes, columns=heroes, dtype=float)

    for hero_a in heroes:
        for hero_b in heroes:
            if hero_a == hero_b:
                # Counter score against oneself is not defined; set as NaN or 0
                counter_scores_df.loc[hero_a, hero_b] = None  # or 0
                continue

            try:
                # Individual win rates
                w_A = winrates_series[hero_a]
                w_B = winrates_series[hero_b]

                # Win rate of Hero A when facing Hero B
                w_A_vs_B = enemy_winrates_df.loc[hero_a, hero_b]

                # Calculate individual contributions relative to 0.5 (50%)
                s_A = w_A - 0.5
                s_B = w_B - 0.5

                # Expected win rate of Hero A against Hero B
                expected_w_A_vs_B = 0.5 + (s_A - s_B)

                counter_score = w_A_vs_B - expected_w_A_vs_B
                counter_scores_df.loc[hero_a, hero_b] = counter_score
            except KeyError:
                counter_scores_df.loc[hero_a, hero_b] = None

    return counter_scores_df

def compute_selected_heroes_scores(scores_df, selected_heroes):
    all_heroes = set(scores_df.index)
    available_heroes = all_heroes - set(selected_heroes)
    total_scores = {}

    for hero in available_heroes:
        total_score = 0
        for selected_hero in selected_heroes:
            try:
                # Get the counter score of 'hero' against 'selected_hero'
                score = scores_df.loc[hero, selected_hero]
                if pd.notna(score):
                    total_score += score
            except KeyError:
                # Handle missing data; skip if data is not available
                continue
        # Store the total counter score
        total_scores[hero] = total_score
        
    selected_heroes_scores_df = pd.Series(total_scores).to_frame("score")

    return selected_heroes_scores_df

def identify_exceptional_interactions(scores_df, lower_quantile=0.10, upper_quantile=0.90):
    """
    Identifies exceptional synergy and counter interactions based on quantile thresholds.
    Each cell in the returned DataFrames holds:
    -1: Exceptionally bad interaction
     0: Normal interaction
     1: Exceptionally good interaction

    Parameters:
    - synergy_scores_df: DataFrame of synergy scores between hero pairs.
    - lower_quantile: Lower quantile threshold (e.g., 0.10 for 10th percentile).
    - upper_quantile: Upper quantile threshold (e.g., 0.90 for 90th percentile).

    Returns:
    - synergy_interaction_df: DataFrame with integer values indicating synergy interactions.
    """

    heroes = scores_df.index
    n = len(heroes)

    mask = ~np.isnan(scores_df.values) & ~np.eye(n, dtype=bool)
    synergy_values = scores_df.values[mask]

    synergy_lower_threshold = np.quantile(synergy_values, lower_quantile)
    synergy_upper_threshold = np.quantile(synergy_values, upper_quantile)

    exceptionnal_interaction_df = pd.DataFrame(0, index=heroes, columns=heroes)
    np.fill_diagonal(exceptionnal_interaction_df.values, 0) # Set diagonal elements to 0 (a hero cannot interact with itself)

    exceptionnal_interaction_df[scores_df >= synergy_upper_threshold] = 1   # Exceptionally good synergy
    exceptionnal_interaction_df[scores_df <= synergy_lower_threshold] = -1  # Exceptionally bad synergy
    np.fill_diagonal(exceptionnal_interaction_df.values, 0)

    return exceptionnal_interaction_df

if __name__ == "__main__":
    import yaml
    import pandas as pd

    with open("2024-09-21.yaml") as f:
        data = yaml.load(f, Loader=yaml.FullLoader)

    winrates_per_bracket, enemy_winrates_df, ally_winrates_df = create_winrate_enemy_synergy_dfs(data)
    counter_scores_df = compute_counter_scores(winrates_per_bracket, enemy_winrates_df)
    synergy_scores_df = compute_synergy_scores(winrates_per_bracket, ally_winrates_df)
    exceptionnal_synergy_df = identify_exceptional_interactions(synergy_scores_df, lower_quantile=0.10, upper_quantile=0.90)
    exceptionnal_counters_df = identify_exceptional_interactions(counter_scores_df, lower_quantile=0.10, upper_quantile=0.90)


    enemy_suggestions_df = suggest_heroes(winrates_per_bracket, counter_scores_df, selected_heroes=["Faceless Void", "Techies"])
    enemy_suggestions_df.sort_values("score", ascending=False).head(10)

    ally_suggestions_df = suggest_heroes(winrates_per_bracket, synergy_scores_df, selected_heroes=["Grimstroke", "Lich"])
    ally_suggestions_df.sort_values("score", ascending=False).head(10)

    enemy_heroes = ["Faceless Void", "Techies"]
    ally_heroes = ["Grimstroke", "Lich"]
    suggestions_df = suggest_heroes_from_ally_and_enemy(
        winrates_per_bracket, 
        counter_scores_df, 
        synergy_scores_df, 
        enemy_heroes=enemy_heroes, 
        ally_heroes=ally_heroes
    )

    print("Suggestions for enemy heroes:")
    print(suggestions_df.sort_values("score", ascending=False).head(10))
    