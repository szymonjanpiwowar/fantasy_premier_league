#!/usr/bin/python

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
        from datetime import datetime, timedelta
        import pandas as pd
        events = pd.DataFrame(self.bootstrapData['events'])
        today = datetime.now()
        today_ts = today.timestamp()
        epoch_del = events.loc[events.deadline_time_epoch > today_ts]
        deadline_ts = epoch_del.iloc[0].deadline_time_epoch
        days_to_deadline = (deadline_ts - today_ts) / 86400.00
        return days_to_deadline

    def get_current_gameweek(self):
        from datetime import datetime, timedelta
        import pandas as pd
        events = pd.DataFrame(self.bootstrapData['events'])
        today = datetime.now()
        today_ts = today.timestamp()
        epoch_del = events.loc[events.deadline_time_epoch > today_ts]
        upcoming = int(epoch_del.name.iloc[0].split()[1])
        return upcoming - 1

    def get_forwards(self):
        from pandas import DataFrame
        players = DataFrame(self.bootstrapData['elements'])
        print(players.columns)
        print(players[['web_name', 'chance_of_playing_this_round']])

    def get_expected_points(self):
        # set-up
        cgw = self.get_current_gameweek()
        # general
        points_for_lt60_minutes = 1.0
        points_for_gt60_minutes = 2.0
        points_per_assist = 3.0
        points_per_yc = -1.0
        points_per_rc = -3.0
        points_per_og = -2.0

        # goalkeeper related points
        points_per_gk_goal = 6.0
        points_per_3saves = 1.0
        points_per_saved_pen = 5.0
        points_per_clean_sheet = 4.0
        points_per_2conceded_goals = -2.0

        # defender related points
        points_per_def_goal = points_per_gk_goal
        points_per_clean_sheet = points_per_clean_sheet

        # The likelihood say that the playtime is distributed normally
        # so, we need to calculate the average and standard deviation on that value
        # then we need to plug in our values
        # E(p>0) + E(p>60)
        # Expected Points = Expected_Goals*PPG
        #                 = Expected_Assists*PPA
        #                 = Expected_Bonus
        #                 = Expected_Minutes -> E(p>0) + E(p>60)
        #                 =
        self.goalkeepers['EXP'] = (self.goalkeepers['SAVES']/3.0*cgw)*points_per_3saves \
                                  + 2


class Managers:
    def __init__(self):
        self.managers = []

    def add_manager(self, manager):
        assert type(manager) is Manager
        self.managers.append(manager)

    def __str__(self):
        # Table -> sort these by rank
        # print:
        manStr = ''
        for manager in self.managers:
            manStr += "{}\n".format(manager.__str__())
        return manStr

    def create_chips_used_table(self):
        pass

    def get_most_benched_points(self):
        highestPoB, lowestPoB = -1, 1e9
        for manager in self.managers:
            managerPoB = manager.points_on_bench_in_pastGW
            try:
                assert type(managerPoB) is int
                if managerPoB > highestPoB:
                    manager_with_mostPoB = manager.manager_name
                    highestPoB = managerPoB
                if managerPoB < lowestPoB:
                    manager_with_leastPoB = manager.manager_name
                    lowestPoB = managerPoB
            except AssertionError:
                print("Incorrect type has been returned by points on bench attribute.")
        return "{} had the least benched points of {}.\n" \
               "{} had the most benched point of {}.".format(manager_with_leastPoB, lowestPoB,
                                                             manager_with_mostPoB, highestPoB)

class Manager:
    def __init__(self, id, name, team, league, old):
        from os import getenv
        self.manager_id = id
        self.manager_name = name
        self.manager_team = team
        self.manager_league = league
        self.isOld = old
        self.team_points = 0
        self.league_rank = 0
        self.chips_used = ()
        self.current_subs = []
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
        # in future this should be gameweek = Bootstrap().get_gameweek()
        picks_url = "https://fantasy.premierleague.com/api/entry/" \
                    "{}/event/{}/picks/".format(self.manager_id, BootStrap().get_current_gameweek())
        session = requests.session()
        picks_data = session.get(picks_url)
        picks_data = json.loads(picks_data.content)
        pastGW = BootStrap().get_current_gameweek()
        currentGW = pastGW + 1
        for gameWeek in range(1, currentGW + 1, 1):
            # Extract chips data
            try:
                if picks_data['active_chip'] is not None:
                    self.chips_used.append([gameWeek, picks_data['active_chip']])
            except KeyError:
                print("Skipping: The user {} created their team past GW{}".format(self.manager_name, gameWeek))
                continue
            if gameWeek == pastGW:
                self.points_on_bench_in_pastGW = picks_data['entry_history']['points_on_bench']
            # Extract upcoming gameWeek data ...
            # This includes the substitutions made and captain used!
            elif gameWeek == currentGW:
                active_subs = picks_data['automatic_subs']
                for sub in active_subs:
                    self.current_subs.append([sub['element_in'], sub['element_out']])
                gameWeek_picks = picks_data['picks']
                for player in gameWeek_picks:
                    if player['is_captain']:
                        self.current_captain = player['element']
                        break
            else:
                print("different week")


class ClassicLeague:
    def __init__(self, id, name):
        import logging
        from os import getenv
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

        def add_managers(manager_data, old=True):
            for entry in manager_data:
                uid = entry['entry']
                team = entry['entry_name']
                name = "{} {}".format(entry['player_first_name'], entry['player_last_name'])
                self.managers.add_manager(Manager(uid, name, team, self.league_name, old))
        # Method starts here ...
        login_url = "https://users.premierleague.com/accounts/login/"
        league_url = 'https://fantasy.premierleague.com/' \
                     'api/leagues-classic/{}/standings'.format(self.league_id)
        session = requests.session()
        ld = session.get(league_url)
        league_data = json.loads(ld.content)
      #  print(league_data)
        # Now that we have the league data, we need to get all of the data that we need ...
        # 1. New Entries to the league.
        add_managers(league_data['new_entries']['results'], False)
        print(self.managers)
        print(self.managers.get_most_benched_points())


if __name__ == "__main__":
    cLeague = ClassicLeague(1026637, 'Jacobs FPL S4')


