from supermodel.inning_simulator import InningInputs, simulate_innings

def test_stronger_home_profile_wins_more_than_half():
    result = simulate_innings(InningInputs(
        away_starter_ra9=5.0, home_starter_ra9=3.0,
        away_bullpen_ra9=4.8, home_bullpen_ra9=3.5,
        away_offense_factor=0.95, home_offense_factor=1.08,
    ), n=10_000)
    assert result['home_win_probability'] > 0.5
