#!/usr/bin/python

class Fixtures:
    def __init__(self, gameweek, team_names):
        self.teams = team_names
        self.gameweek = gameweek
        self.updated = False
        self.__load_upcoming_fixture()

    def __load_upcoming_fixture(self):
        import requests
        import json
        from pandas import DataFrame
        from datetime import datetime
        url = "https://fantasy.premierleague.com/api/fixtures?event={}".format(self.gameweek)
        response = requests.get(url)
        extracted_fixture_data = json.loads(response.content)
        if "updated" in extracted_fixture_data:
            self.updated = True
            return
        data, columns = [], ['id', 'FDR', 'kick_off_time']
        try:
            for fixture in extracted_fixture_data:
                diff_h = fixture['team_h_difficulty']
                diff_a = fixture['team_a_difficulty']
                data.append([fixture['team_h'], 1.0 / diff_h, datetime.strptime(fixture['kickoff_time'], '%Y-%m-%dT%H:%M:%SZ')])
                data.append([fixture['team_a'], 1.0 / diff_a, datetime.strptime(fixture['kickoff_time'], '%Y-%m-%dT%H:%M:%SZ')])
            data = DataFrame(data, columns=columns).sort_values(by='id', ascending=True)
            data['team_name'] = data.id.map(self.teams.set_index('id').name)
            self.fixture_data = data

        except Exception as e:
            self.fixture_data = DataFrame()

    def get_time_to_final_kickoff(self):
        """Returns the time to the final kick off in seconds."""
        from datetime import datetime
        # Check if the game is being updated ... if so return something ridiculous
        if self.updated:
            return 1E9
        kick_offs = self.fixture_data.sort_values(by='kick_off_time', ascending=False)
        return kick_offs['kick_off_time'].iloc[0].timestamp() - datetime.now().timestamp()


class Players:
    def __init__(self, bootstrap):
        from pandas import DataFrame
        self.bootstrap = bootstrap.bootstrapData
        self.currentGW = bootstrap.get_current_gameweek()
        self.__load_players()

    def __str__(self):
        return self.players.to_string()

    def __load_players(self):
        from pandas import DataFrame
        players = []
        for player in self.bootstrap['elements']:
            players.append([player['id'], player['web_name']])
        self.players = DataFrame(players, columns=['id', 'web_name'])

    def load_players_and_calculate_xp(self, upcoming_fixture_data):
        import requests
        import json
        from math import exp, isnan
        from datetime import datetime
        import pandas as pd
        from statistics import mean, stdev, StatisticsError
        from scipy import stats
        import numpy as np
        dt_player = {}
        # General points - applicable to all positions
        points_per_yc = -1.0
        points_per_rc = -3.0
        points_per_og = -2.0
        points_per_3saves = 1.0
        points_per_saved_pen = 5.0
        points_per_missed_pen = -2.0
        points_per_assist = 3.0
        gwc = self.currentGW / 38.0
        players = []
        for player in self.bootstrap['elements']:
            today_ts = datetime.today().timestamp()
            player_id = player['id']
            fdr = float(upcoming_fixture_data.loc[upcoming_fixture_data['id'] == player['team']]['FDR'])
            # setup position specific points ...
            url = "https://fantasy.premierleague.com/api/element-summary/{}/".format(player_id)
            response = requests.get(url)
            extracted_player_data = json.loads(response.content)
            s = 0.1
            T = 1.0 / s
            weightM = []
            playing_chance = player['chance_of_playing_this_round']
            playing_chance = 1.0 if playing_chance is None else playing_chance / 100.0
            player_data = {
                'minutes': [],
                'pm00': 0.0,
                'pm60': 0.0,
                'goals_scored': [],
                'assists': [],
                'clean_sheets': [],
                'goals_conceded': [],
                'own_goals': [],
                'bonus': [],
                'penalties_saved': [],
                'penalties_missed': [],
                'yellow_cards': [],
                'red_cards': [],
                'saves': [],
                'value': player['now_cost']
            }
            player_points = {
                'web_name': player['web_name'],
                'position': 'Unknown',
                'xPoints': 0.0,
                'cost_to_points': 0.0,
            }
            # Goalkeeper - set goalkeeper specific points
            if player['element_type'] == 1:
                player_points['position'] = 'Goalkeeper'
                points_per_goal = 6.0
                points_per_clean_sheet = 4.0
                points_per_2conceded_goals = -1.0
            elif player['element_type'] == 2:
                player_points['position'] = 'Defender'
                points_per_goal = 6.0
                points_per_clean_sheet = 4.0
                points_per_2conceded_goals = -1.0
            elif player['element_type'] == 3:
                player_points['position'] = 'Midfielder'
                points_per_goal = 5.0
                points_per_assist = 3.0
                points_per_clean_sheet = 1.0
                points_per_2conceded_goals = 0.0
            else:
                player_points['position'] = 'Forward'
                points_per_goal = 4.0
                points_per_2conceded_goals = 0.0
            # Use historical data of player to determine the likely number of
            # goals, assists etc. that they will have for the next game.
            for historyData in extracted_player_data['history']:
                fixture_dt = datetime.strptime(historyData['kickoff_time'], '%Y-%m-%dT%H:%M:%SZ')
                fixture_ts = fixture_dt.timestamp()
                timedelta = (today_ts - fixture_ts) / 86400.0
                # assign weight to each fixture based on how far in the past it was ...
                weightM.append(s * exp(-timedelta / T))
                player_data['minutes'].append(historyData['minutes'])
                player_data['goals_scored'].append(historyData['goals_scored'])
                player_data['assists'].append(historyData['assists'])
                player_data['clean_sheets'].append(historyData['clean_sheets'])
                player_data['goals_conceded'].append(historyData['goals_conceded'])
                player_data['own_goals'].append(historyData['own_goals'])
                player_data['bonus'].append(historyData['bonus'])
                player_data['penalties_saved'].append(historyData['penalties_saved'])
                player_data['penalties_missed'].append(historyData['penalties_missed'])
                player_data['yellow_cards'].append(historyData['yellow_cards'])
                player_data['red_cards'].append(historyData['red_cards'])
                player_data['saves'].append(historyData['saves'])
            # Normalise weight matrix - this tries to adjust how the player actions
            # are scored. The most recent events are given higher weight.
            try:
                weightM = [W / sum(weightM) for W in weightM]
            except ZeroDivisionError or RuntimeWarning as e:
                print("Error: Unable to divide by zero!")
            # calculate the likelihood of playing at least a minute/ 60 minutes
            try:
                min_dist = stats.norm(mean(player_data['minutes']), stdev(player_data['minutes']))
                k00 = min_dist.cdf(0)
                k60 = min_dist.cdf(60)
            except StatisticsError:
                k00 = 0.0
                k60 = 0.0
            pm00 = 0.0 if isnan(k00) else k00
            pm60 = 0.0 if isnan(k60) else k60
            # TODO: Create a loop that deals with this ...
            try:
                xPg = points_per_goal * (np.dot(player_data['goals_scored'], weightM)
                                         + gwc * (3.0 - fdr) * stdev(player_data['goals_scored']))
            except StatisticsError:
                xPg = points_per_goal * (np.dot(player_data['goals_scored'], weightM))
            try:
                xPa = points_per_assist * (np.dot(player_data['assists'], weightM)
                                           + gwc * (3.0 - fdr) * stdev(player_data['assists']))
            except StatisticsError:
                xPa = points_per_assist * (np.dot(player_data['assists'], weightM))
            try:
                xCs = points_per_clean_sheet * (np.dot(player_data['clean_sheets'], weightM)
                                                + gwc * (3.0 - fdr) * stdev(player_data['clean_sheets']))
            except StatisticsError:
                xCs = points_per_clean_sheet * (np.dot(player_data['clean_sheets'], weightM))
            try:
                xGc = 0.5 * points_per_2conceded_goals * (np.dot(player_data['goals_conceded'], weightM)
                                                          + gwc * (fdr - 3.0) * stdev(player_data['goals_conceded']))
            except StatisticsError:
                xGc = 0.5 * points_per_2conceded_goals * (np.dot(player_data['goals_conceded'], weightM))
            try:
                xYc = points_per_yc * (np.dot(player_data['yellow_cards'], weightM)
                                       + gwc * (fdr - 3.0) * stdev(player_data['yellow_cards']))
            except StatisticsError:
                xYc = points_per_yc * (np.dot(player_data['yellow_cards'], weightM))
            try:
                xRc = points_per_rc * (np.dot(player_data['red_cards'], weightM)
                                       + gwc * (fdr - 3.0) * stdev(player_data['red_cards']))
            except StatisticsError:
                xRc = points_per_rc * (np.dot(player_data['red_cards'], weightM))
            try:
                xSv = points_per_3saves * ((np.dot(player_data['saves'], weightM)
                                            + gwc * (fdr - 3.0) * stdev(player_data['saves'])) / 3.0)
            except StatisticsError:
                xSv = points_per_3saves * ((np.dot(player_data['saves'], weightM)) / 3.0)
            xOg = np.dot(player_data['own_goals'], weightM) * points_per_og
            xBo = np.dot(player_data['bonus'], weightM)
            xPs = np.dot(player_data['penalties_saved'], weightM) * points_per_saved_pen
            xPm = np.dot(player_data['penalties_missed'], weightM) * points_per_missed_pen
            player_points['xPoints'] = playing_chance * (xPg + xPa + xCs +
                                                         xGc + xOg + xBo + xPs + xPm +
                                                         xYc + xRc + xSv +
                                                         pm00 + pm60
                                                         )
            # Points scored per pound spent.
            player_points['cost_to_points'] = player_points['xPoints'] / player_data['value']
            players.append(player_points)
        self.players = pd.DataFrame(players)

    def get_player_data(self, pos, sort_att, asc, entr):
        matching = self.players[self.players['position'] == pos] \
            .sort_values(by=sort_att, ascending=asc) \
            .head(entr)
        return matching[['web_name', 'xPoints', 'cost_to_points']].rename(columns={'web_name': 'Name',
                                                                                   'xPoints': 'Expected Points',
                                                                                   'cost_to_points': 'Cost / Expected Points'})


class BootStrap:
    def __init__(self):
        self.__load_bootstrap_data()

    def __load_bootstrap_data(self):
        import requests
        import json
        url = 'https://fantasy.premierleague.com/api/bootstrap-static/'
        response = requests.get(url)
        self.bootstrapData = json.loads(response.content)

    def get_days_to_deadline(self):
        from datetime import datetime
        import pandas as pd
        events = pd.DataFrame(self.bootstrapData['events'])
        today = datetime.now()
        today_ts = today.timestamp()
        epoch_del = events.loc[events.deadline_time_epoch > today_ts]
        deadline_ts = epoch_del.iloc[0].deadline_time_epoch
        days_to_deadline = (deadline_ts - today_ts) / 86400.00
        return days_to_deadline

    def get_current_gameweek(self):
        from datetime import datetime
        import pandas as pd
        events = pd.DataFrame(self.bootstrapData['events'])
        today = datetime.now()
        today_ts = today.timestamp()
        epoch_del = events.loc[events.deadline_time_epoch > today_ts]
        upcoming = int(epoch_del.name.iloc[0].split()[1])
        return upcoming - 1

    def get_teams(self):
        from pandas import DataFrame
        teams_data = DataFrame(self.bootstrapData['teams'])
        return teams_data[['id', 'name']]


class Managers:
    def __init__(self):
        self.managers = []
        self.no_managers = len(self.managers)
        self.top_points = -1

    def add_manager(self, manager):
        assert type(manager) is Manager
        self.managers.append(manager)
        self.no_managers += 1
        if manager.team_points > self.top_points:
            self.top_points = manager.team_points

    def create_manager_table(self, bootstrap):
        from pandas import DataFrame
        table, row, columns = [], [], []
        table_columns_added = False
        pl_players = Players(bootstrap).players
        map_chip_name = {'wildcard': 'Wildcard', '3xc': 'Triple Captain',
                         'bboost': 'Bench Boost', 'freehit': 'Free Hit'}
        for manager in self.managers:
            if not table_columns_added:
                columns.append("Rank")
                columns.append("Name")
                for chip_header in manager.chips_used.keys():
                    columns.append(map_chip_name[chip_header])
                columns.append("Points")
                columns.append("To leader")
                columns.append("Points Benched")
                columns.append("Transfer Penalty Points")
                table_columns_added = True
            manager_crank = manager.league_rank
            manager_orank = manager.league_last_rank
            if manager_crank > manager_orank:
                rank = "{} \u2193".format(manager_crank)
            elif manager_crank == manager_orank:
                rank = "{} \u2192".format(manager_crank)
            else:
                rank = "{} \u2191".format(manager_crank)
            row.append(rank)
            row.append(manager.manager_name)
            for chip in manager.chips_used.values():
                row.append(chip)
            row.append(manager.team_points)
            distance_to_leader = manager.team_points - self.top_points
            row.append(distance_to_leader)
            row.append(manager.points_on_bench_in_pastGW)
            row.append(manager.total_penalty_points)
            table.append(row)
            row = []
        return DataFrame(table, columns=columns).sort_values(by='Points', ascending=False)

    def get_most_improved_managers(self):
        highest_score_of_gw = -1
        highest_scoring_managers = []
        for manager in self.managers:
            if manager.current_gw_points > highest_score_of_gw:
                highest_scoring_managers.clear()
                highest_scoring_managers.append(manager.manager_name)
                highest_score_of_gw = manager.current_gw_points
            elif manager.current_gw_points == highest_scoring_managers:
                highest_scoring_managers.append(manager.manager_name)
            else:
                highest_score_of_gw = highest_score_of_gw
        # turn highest_scoring_managers into string
        hsm = ''
        final_index = len(highest_scoring_managers) - 1
        for index, manager in enumerate(highest_scoring_managers):
            if index == final_index:
                hsm += manager
            else:
                hsm += "{}, ".format(manager)
        return hsm


class Manager:
    def __init__(self, id, name, team, league, rank, last_rank, points):
        from os import getenv
        self.manager_id = id
        self.manager_name = name
        self.manager_team = team
        self.manager_league = league
        self.team_points = points
        self.league_last_rank = last_rank
        self.league_rank = rank
        self.total_penalty_points = 0
        self.chips_used = {'wildcard': [False, 0],
                           '3xc': [False, 0],
                           'bboost': [False, 0],
                           'freehit': [False, 0]
                           }
        self.current_subs = []
        self.current_gw_points = 0
        self.current_captain = None
        self.points_on_bench_in_pastGW = None
        self.__load_user_data()
        self.__load_user_picks()

    def __str__(self):
        return "{}, manager of {} scored {} and had {} points of bench".format(self.manager_name,
                                                                               self.manager_team,
                                                                               self.team_points,
                                                                               self.points_on_bench_in_pastGW)
        # Print name surname wildcard free hit bench boost triple capitan points best_scorer points

    def __load_user_data(self):
        import json
        import requests
        import pandas as pd
        login_url = "https://users.premierleague.com/accounts/login/"
        manager_url = "https://fantasy.premierleague.com/api/entry/" \
                      "{}/".format(self.manager_id)
        session = requests.session()
        manager_data = session.get(manager_url)
        manager_data = json.loads(manager_data.content)
        # Extract information about user in the league.
        manager_league_data = pd.DataFrame(manager_data['leagues']['classic'])
        columns = manager_league_data['name']
        manager_league_data = manager_league_data.transpose()
        manager_league_data.columns = columns
        # Extract only data about the league for which manager has been assigned to
        manager_league_data = manager_league_data[self.manager_league]

    def __load_user_picks(self):
        import json
        import requests
        current_GW = BootStrap().get_current_gameweek()
        upcoming_GW = current_GW + 1
        # Extract data from all GW about the users!
        for gameweek in range(1, upcoming_GW, 1):
            picks_url = "https://fantasy.premierleague.com/api/entry/" \
                        "{}/event/{}/picks/".format(self.manager_id, gameweek)
            session = requests.session()
            picks_data = session.get(picks_url)
            picks_data = json.loads(picks_data.content)
            # Extract chips data
            try:
                chip_used = picks_data['active_chip']
                if chip_used is not None:
                    self.chips_used[chip_used] = [True, gameweek]
                self.total_penalty_points += picks_data['entry_history']['event_transfers_cost']
                if gameweek == current_GW:
                    self.current_gw_points = picks_data['entry_history']['points']
                    self.points_on_bench_in_pastGW = picks_data['entry_history']['points_on_bench']
                # Extract upcoming gameWeek data ...
                # This includes the substitutions made and captain used!
                elif gameweek == upcoming_GW:
                    active_subs = picks_data['automatic_subs']
                    for sub in active_subs:
                        self.current_subs.append([sub['element_in'], sub['element_out']])
                    gameWeek_picks = picks_data['picks']
                    for player in gameWeek_picks:
                        if player['is_captain']:
                            self.current_captain = player['element']
                            break
            except KeyError:
                print("Skipping: The user {} created their team past GW{}. "
                      "Trying different week.".format(self.manager_name, gameweek))
                continue


class ClassicLeague:
    def __init__(self, id, name):
        import logging
        try:
            assert type(id) is int
        except AssertionError:
            logging.error("Please specify correct type for id")
            return
        self.league_id = id
        self.league_name = name
        self.managers = Managers()
        self.currentGW = 0
        self.__load_league_data()

    def __str__(self):
        return ""

    def __load_league_data(self):
        import json
        import requests
        import pandas as pd

        def add_managers(manager_data, new_entry):
            for entry in manager_data:
                uid = entry['entry']
                team_name = entry['entry_name']
                if not new_entry:
                    name = entry['player_name']
                    points, rank, last_rank = entry['total'], entry['rank'], entry['last_rank']
                else:
                    fist_name = entry['player_first_name']
                    last_name = entry['player_last_name']
                    name = "{} {}".format(fist_name, last_name)
                    points, rank, last_rank = 0, "N/A", "N/A"
                self.managers.add_manager(Manager(uid, name, team_name, self.league_name, rank, last_rank, points))

        # Method starts here ...
        league_url = 'https://fantasy.premierleague.com/' \
                     'api/leagues-classic/{}/standings'.format(self.league_id)
        session = requests.session()
        ld = session.get(league_url)
        league_data = json.loads(ld.content)
        # Now that we have the league data, we need to get all of the data that we need ...
        # 1. New Entries to the league.
        add_managers(league_data['new_entries']['results'], True)
        # 2. Add managers from standings
        add_managers(league_data['standings']['results'], False)
