import unittest
from datetime import date
from unittest.mock import patch

from agents import sports_agent


def _entry(team_id, name, played="1", points="3", rank="1"):
    return {
        "team": {"id": team_id, "displayName": name, "logos": [{"href": ""}]},
        "stats": [
            {"name": "rank", "displayValue": rank},
            {"name": "gamesPlayed", "displayValue": played},
            {"name": "wins", "displayValue": "1"},
            {"name": "ties", "displayValue": "0"},
            {"name": "losses", "displayValue": "0"},
            {"name": "pointsFor", "displayValue": "1"},
            {"name": "pointsAgainst", "displayValue": "0"},
            {"name": "pointDifferential", "displayValue": "+1"},
            {"name": "points", "displayValue": points},
        ],
    }


def _event(event_id, when, left, right, left_goals, right_goals):
    return {
        "id": event_id,
        "date": when,
        "competitions": [{
            "status": {"type": {"state": "post"}},
            "competitors": [
                {"team": {"id": left}, "score": str(left_goals)},
                {"team": {"id": right}, "score": str(right_goals)},
            ],
        }],
    }


class SportsQuestionTests(unittest.TestCase):
    def setUp(self):
        sports_agent._FEED_CACHE.clear()

    def test_one_read_covers_the_questions_that_failed(self):
        final = sports_agent._parse_question("what was the final score of Burundi today?")
        self.assertEqual(final["intent"], "score")
        self.assertEqual(final["team"], "Burundi")
        self.assertEqual(final["label"], "today")
        self.assertIsInstance(final["day"], date)

        last = sports_agent._parse_question("what was the final score of Burundi last time?")
        self.assertEqual(last["intent"], "score")
        self.assertEqual(last["team"], "Burundi")
        self.assertEqual(last["label"], "last time")
        self.assertIsNone(last["day"])

        top = sports_agent._parse_question("what are the 10 top teams in champions league?")
        self.assertEqual(top["intent"], "standing")
        self.assertEqual(top["limit"], 10)
        self.assertEqual(top["competition"][0], "uefa.champions")

        numbered = sports_agent._parse_question("what are the top 10 teams in the champions league?")
        self.assertEqual(numbered["limit"], 10)

        congo = sports_agent._names_in(["congo"], {"home": "Congo DR", "away": "Zambia"})
        self.assertFalse(congo)
        drc = sports_agent._names_in(["drc"], {"home": "Congo DR", "away": "Sierra Leone"})
        self.assertTrue(drc)
        self.assertFalse(sports_agent._names_in(["mali"], {"home": "Somalia", "away": "Ghana"}))
        self.assertTrue(sports_agent._names_in(["mali"], {"home": "Mali", "away": "Chad"}))
        self.assertTrue(sports_agent._names_in(["somalia"], {"home": "Somalia", "away": "Ghana"}))

    def test_final_score_today_uses_the_parsed_team_and_day(self):
        def fake_events(url):
            self.assertIn("soccer/", url)
            return [{
                "home": "Zambia",
                "away": "Burundi",
                "time": "FT",
                "score": "1-1",
                "eid": "1873014",
                "comp": "AFCON qualifying",
            }]

        with patch.object(sports_agent, "_livescore_events", fake_events), patch.object(
            sports_agent, "_livescore_line", lambda event: "Zambia 1-1 Burundi FT"
        ):
            reply = sports_agent._score_on_day("what was the final score of Burundi today?")

        self.assertIn("final score today", reply["text"])
        self.assertEqual(reply["focus"]["team"], "Burundi")
        self.assertNotIn("final Burundi", reply["text"])

    def test_group_schedules_are_requested_together_and_reused(self):
        calls = []

        def fake_schedule(league, team_id):
            calls.append(team_id)
            return [_event("1", "2026-11-13T16:00Z", "10", "20", 1, 1)]

        with patch.object(sports_agent, "_schedule_events", fake_schedule):
            first = sports_agent._finished_table_matches("caf.nations_qual", {"10", "20"}, {"10", "20"})
            second = sports_agent._finished_table_matches("caf.nations_qual", {"10", "20"}, {"10", "20"})

        self.assertEqual(set(calls), {"10", "20"})
        self.assertEqual(first, second)
        self.assertEqual(len(first), 1)

    def test_large_league_uses_the_competition_scoreboard(self):
        ids = {str(number) for number in range(1, 10)}
        urls = []

        def fake_schedule(league, team_id):
            self.assertIn(team_id, ids)
            return [_event("9", "2026-11-04T20:00Z", "1", "99", 1, 0)]

        def fake_json(url):
            urls.append(url)
            return {"events": [_event("9", "2026-11-04T20:00Z", "1", "2", 1, 0), _event("8", "2026-11-04T20:00Z", "3", "4", 2, 2)]}

        with patch.object(sports_agent, "_schedule_events", fake_schedule), patch.object(sports_agent, "_get_json", fake_json):
            matches = sports_agent._competition_table_matches("uefa.champions", ids)

        self.assertEqual(urls, ["https://site.api.espn.com/apis/site/v2/sports/soccer/uefa.champions/scoreboard?dates=20261104"])
        self.assertEqual(len(matches), 2)
        again = sports_agent._competition_table_matches("uefa.champions", ids)
        self.assertEqual(again, matches)
        self.assertEqual(len(urls), 1)

    def test_top_ten_sentence_uses_the_shared_standing_read(self):
        groups = [{
            "name": "League Phase",
            "standings": {
                "seasonDisplayName": "2026-27 UEFA Champions League",
                "entries": [_entry(str(number), f"Club {number}", rank=str(number)) for number in range(1, 37)],
            },
        }]
        with patch.object(sports_agent, "_standings_groups", lambda slug: groups), patch.object(
            sports_agent, "_competition_table_matches", lambda league, team_ids: []
        ):
            reply = sports_agent.sports_reply("what are the 10 top teams in champions league?")

        self.assertIn("Top 10 in 2026-27 UEFA Champions League.", reply["text"])
        self.assertEqual(len(reply["card"]["rows"]), 10)
        self.assertNotIn("Top 36", reply["text"])


if __name__ == "__main__":
    unittest.main()
