"""Sports answers from TheSportsDB and English Wikipedia, or an explicit gap."""

import os
import random
import re
import unicodedata
from datetime import datetime, timedelta
from zoneinfo import ZoneInfo

import requests

_API = "https://www.thesportsdb.com/api/v1/json/123"
_HEADERS = {"User-Agent": "Mozilla/5.0"}
_KAMPALA = ZoneInfo("Africa/Kampala")
_SPORT_SITE = (
    ("premier league", "Premier League", "https://www.premierleague.com/"),
    ("la liga", "La Liga", "https://www.laliga.com/"),
    ("bundesliga", "Bundesliga", "https://www.bundesliga.com/"),
    ("serie a", "Serie A", "https://www.legaseriea.it/"),
    ("ligue 1", "Ligue 1", "https://www.ligue1.com/"),
    ("champions league", "UEFA", "https://www.uefa.com/"),
    ("afcon", "CAF", "https://www.cafonline.com/"),
    ("africa cup", "CAF", "https://www.cafonline.com/"),
    ("african cup", "CAF", "https://www.cafonline.com/"),
    ("nba", "NBA", "https://www.nba.com/"),
    ("formula 1", "Formula 1", "https://www.formula1.com/"),
    ("ufc", "UFC", "https://www.ufc.com/"),
    ("wimbledon", "Wimbledon", "https://www.wimbledon.com/"),
    ("olympic", "Olympics", "https://olympics.com/"),
)
_ALIASES = {
    "drc": "DR Congo",
    "dr congo": "DR Congo",
    "rdc": "DR Congo",
    "congo kinshasa": "DR Congo",
    "democratic republic of congo": "DR Congo",
    "democratic republic of the congo": "DR Congo",
    "man utd": "Manchester United",
    "man united": "Manchester United",
}
_SQUAD_ASK = re.compile(
    r"\b(?:11|eleven)\b.{0,40}\b(?:start\w*|players?)\b"
    r"|\b(?:start\w*|players?)\b.{0,40}\b(?:11|eleven)\b"
    r"|\bline[- ]?up\b"
    r"|\b(?:list of|squad|roster)\b.{0,40}\bplayers?\b"
    r"|\bplayers?\s+(?:of|for)\b",
    re.IGNORECASE,
)
_SKIP = {
    "the", "a", "an", "next", "last", "latest", "match", "result", "score",
    "live", "today", "tomorrow", "of", "for", "in", "on", "vs", "versus",
    "when", "does", "do", "is", "are", "which", "play", "playing", "fixture",
    "fixtures", "upcoming", "what", "who", "won", "against", "club", "team",
    "time", "his", "her", "their", "about", "age", "current", "happening",
    "football", "soccer", "matches", "games", "scheduled", "its",
}
_CONCEPTS = (
    (r"difference between football and rugby",
     "Association football uses a round ball and eleven players a side, and outfield players may not handle the ball. Rugby uses an oval ball, allows carrying the ball, and scores mainly by tries. A league is a season-long table. A tournament is a bracket or a short event that crowns a winner."),
    (r"difference between a league and a tournament",
     "A league ranks teams across a season, usually by points. A tournament is a separate event, often with a group stage or a knockout bracket, and it ends when a champion is decided."),
    (r"how many players are on a standard football",
     "A standard association-football team has eleven players on the pitch, including the goalkeeper. Competitions set their own substitute limits."),
    (r"purpose of the olympic games",
     "The Olympic Games are a multi-sport meeting of national teams and athletes, held every four years in summer and winter editions. The sports on the programme change by edition."),
    (r"which sports use a referee",
     "Football, rugby, basketball, and boxing all use a referee to apply the laws during play. The title and the powers differ by sport."),
    (r"scoring system work in basketball",
     "In basketball a shot inside the arc is worth two points, a shot from beyond the arc is worth three, and a free throw is worth one. The team with more points at the end of the regulation periods wins, unless overtime is needed."),
    (r"grand slam in tennis",
     "A tennis Grand Slam is one of the four major tournaments: the Australian Open, the French Open, Wimbledon, and the US Open. Winning all four in one calendar year is a calendar-year Grand Slam."),
    (r"formula 1 determine its champion",
     "Formula 1 awards points for finishing positions in each Grand Prix. The driver and the constructor with the most points at the end of the season are the champions. The points table is set by the FIA regulations for that season."),
    (r"difference between boxing and mma",
     "Boxing is fought with the fists, under rounds and a weight class. MMA allows strikes and grappling, also in rounds and weight classes. They are different rule sets, not the same sport."),
    (r"offside rule",
     "In association football an attacker is offside when a teammate plays the ball and that attacker is nearer the opponent's goal line than both the ball and the second-last opponent, and is involved in active play. It is judged at the moment the ball is played, not when the attacker receives it."),
    (r"when is a penalty awarded",
     "A penalty kick is awarded when a player commits a direct free-kick offence inside the opponent's penalty area."),
    (r"after a red card",
     "A sent-off player leaves the pitch and cannot be replaced. The team continues with one fewer player. The competition decides any further suspension."),
    (r"how does var work",
     "VAR is a video review. The referee can overturn a decision only for a clear error on a goal, a penalty, a direct red card, or mistaken identity. The referee remains the decision-maker."),
    (r"how many substitutions",
     "The number of substitutes depends on the competition. Many senior football competitions allow five substitutes. I will not treat that number as universal without that competition's regulations."),
    (r"what is extra time",
     "Extra time is an added period played when a knockout match is level after 90 minutes and the competition requires a winner. If it is still level, a penalty shootout may follow."),
    (r"penalty shootout",
     "In a football penalty shootout each team takes kicks from the penalty mark, alternating. Each team takes five kicks unless the result is already decided, then sudden death continues if the scores are level."),
    (r"away-goals rule",
     "The away-goals rule used to break a tie by counting goals scored away from home. UEFA removed it from its club competitions from 2021/22. A competition that still uses it will say so in its own regulations."),
    (r"false nine",
     "A false nine is a centre-forward who drops away from the last defender into midfield, so a teammate can run into the space left behind."),
    (r"4-3-3|4 3 3",
     "A 4-3-3 lines up four defenders, three midfielders, and three forwards. The shape describes the starting positions, not a guarantee of how the team defends."),
    (r"high press",
     "High pressing means the team tries to win the ball back in the opponent's half, close to the opponent's goal, instead of waiting near its own penalty area."),
    (r"man-marking and zonal",
     "Man-marking assigns a defender to follow a specific opponent. Zonal marking assigns each defender to an area of the pitch. Teams often mix the two."),
    (r"what is a release clause",
     "A release clause is a fee written into a contract. If a buying club pays that fee and the other conditions are met, the selling club must allow the player to talk to that club. The exact effect depends on the contract and the league's rules."),
    (r"difference between a loan and a permanent",
     "A loan moves a player to another club for a limited period. The registration usually returns to the owning club. A permanent transfer moves the registration to the new club."),
    (r"difference between atp and wta",
     "The ATP runs the main men's professional tennis tour. The WTA runs the main women's professional tennis tour. They are separate tours with their own rankings."),
    (r"how points are awarded in rugby",
     "In rugby union a try is worth five points, a conversion two, a penalty goal three, and a drop goal three. Rugby league uses its own values, so the code matters."),
)


def sports_reply(message, focus=None, conversation=None):
    """Answer a sports question, or return None when the message is not about sport."""
    focus = dict(focus or {})
    text = _bind(re.sub(r"\s+", " ", (message or "")).strip(), focus, conversation)
    if not text:
        return None
    concept = _concept(text)
    if concept:
        return concept
    if _SQUAD_ASK.search(text):
        return _lineup_answer(text, focus)
    if re.search(r"\b(injur\w*|suspended|doubtful)\b", text, re.IGNORECASE):
        return {"text": "I don't have a confirmed injury, suspension, or return date for that, so I won't invent one."}
    if re.search(r"\b(likely|predict|chances|who will win)\b", text, re.IGNORECASE):
        return {"text": "That would be a prediction, not a result. I won't name a winner or a probability as a fact."}
    if re.search(r"\b(sign next|interested in|negotiat|free agents|transfer developments)\b", text, re.IGNORECASE):
        return _no_rumour(text, focus)
    if re.search(r"\b(scored|scorer|scorers)\b", text, re.IGNORECASE):
        return _scorer_answer(text, focus)
    if re.search(r"\blive\b", text, re.IGNORECASE) and re.search(r"\bscore", text, re.IGNORECASE):
        return _livescore_answer(text)
    if re.search(r"\byesterday\b", text, re.IGNORECASE) and re.search(r"\b(result|score|match|matches|game|games)\b", text, re.IGNORECASE):
        return _yesterday_answer(text)
    board = _competition_board(text)
    if board:
        return board
    playing = _playing_answer(text, focus)
    if playing:
        return playing
    if re.search(r"\b(today|live|tomorrow|this week|this month)\b", text, re.IGNORECASE) and re.search(
        r"\b(match|matches|game|games|fixture|fixtures|live|afcon|playing)\b", text, re.IGNORECASE
    ):
        return _day_answer(text)
    if re.search(r"\b(who is|born|position|how old|nationality|age)\b", text, re.IGNORECASE):
        profile = _player_profile(text)
        if profile:
            return profile
        return None
    if re.search(r"\b(plays for|play for|which club|which team|represent)\b", text, re.IGNORECASE):
        return _player_club(text)
    if re.search(r"\b(career|clubs has|which clubs|joined|trophies|debut)\b", text, re.IGNORECASE):
        return _career(text)
    if re.search(r"\bcompare\b|\bbetter between\b|\bwho is better\b", text, re.IGNORECASE):
        return _compare(text)
    history = _history(text)
    if history:
        return history
    if re.search(r"\b(standing|standings|ranking|rankings)\b", text, re.IGNORECASE) or (
        re.search(r"\btop\s+\d+\b|\b\d+\s+top\b|\btop teams\b", text, re.IGNORECASE) and _named_league(text)
    ):
        table = _standing_answer(text)
        if table:
            return table
    if re.search(r"\bfifa\b", text, re.IGNORECASE) and re.search(r"\b(ranking|rankings|standings|top\s+\d+)\b", text, re.IGNORECASE):
        return _fifa_rankings(text)
    if re.search(r"\b(news|dismissed|broke records)\b", text, re.IGNORECASE):
        return {"text": "I don't have a dated news report for that, so I won't turn a rumour into a confirmed story."}
    direct = _direct_fixture(text, focus)
    if direct:
        return direct
    if not _looks_sports(text):
        return None
    return _fixture_answer(text)


def _direct_fixture(text, focus):
    if re.search(r"\b(starters|starting 11|starting eleven|lineup|line-up|11 players|11 starts|players of that match)\b", text, re.IGNORECASE):
        return _lineup_answer(text, focus)
    earlier = (focus or {}).get("matchup") or ""
    if re.search(r"\bvs\.?\b|\bversus\b", text, re.IGNORECASE):
        return _versus_answer(text)
    if re.search(r"\b(score|last played|last play|last match)\b", text, re.IGNORECASE) or (
        re.search(r"\b(did|has)\b", text, re.IGNORECASE) and re.search(r"\b(win|won)\b", text, re.IGNORECASE)
    ):
        if earlier and not _subject(text):
            return _versus_answer(earlier)
        if re.search(r"\band\b", text, re.IGNORECASE):
            return _versus_answer(re.sub(r"\band\b", " vs ", text, count=1, flags=re.IGNORECASE))
        return _last_answer(text, focus)
    if re.search(r"\bwhen\b", text, re.IGNORECASE) and re.search(r"\bplay", text, re.IGNORECASE):
        return _when_answer(text)
    return None


def _when_answer(text):
    name = _subject(text)
    found = _next_fixture(name) if name else None
    if not found:
        return {"text": f"I couldn't find a next match for {name or 'that team'}, so I won't invent a date."}
    event, team = found
    return {
        "text": f"{_event_line(event)}\n\n{_fixture_source(event)}",
        "focus": {"team": team["name"], "event": event.get("id") or "", "espn_league": event.get("espn_league") or ""},
    }


def _last_answer(text, focus):
    name = _subject(text) or (focus or {}).get("team") or ""
    found = _last_completed(name) if name else None
    if not found:
        return {"text": f"I couldn't find a completed match for {name or 'that team'}, so I won't invent a score."}
    event, team = found
    return {
        "text": f"{_score_line(event)} That was the last listed match.\n\n{_fixture_source(event)}",
        "focus": {"team": team["name"], "event": event.get("id") or "", "espn_league": event.get("espn_league") or ""},
        "card": _match_card(event.get("title") or team["name"], [event]),
    }


def _versus_answer(text):
    parts = re.split(r"\s+\bvs\.?\b\s+|\s+\bversus\b\s+", text, maxsplit=1, flags=re.IGNORECASE)
    if len(parts) < 2:
        return None
    left = _subject(parts[0]) or parts[0]
    right = _subject(parts[1]) or parts[1]
    item = _espn_pick(left)
    if not item:
        return {"text": f"I couldn't find {left} on the football schedule, so I won't invent a score."}
    other = _plain(right)
    found = []
    seen = set()
    for candidate in _espn_items(left) + [_world_cup_item(_espn_pick(left))]:
        if not candidate or not candidate.get("id") or not candidate.get("league"):
            continue
        key = (str(candidate["id"]), candidate["league"])
        if key in seen:
            continue
        seen.add(key)
        for raw in _espn_schedule(candidate):
            event = _read_event(raw, candidate)
            if event and other in _plain(event["title"]):
                found.append(event)
    finished = [event for event in found if event.get("finished") and event.get("home_score") not in (None, "")]
    if finished:
        event = sorted(finished, key=lambda item: item.get("date") or "", reverse=True)[0]
        return {
            "text": f"{_score_line(event)} That was the last listed meeting.\n\n{_fixture_source(event)}",
            "focus": {"team": item.get("displayName") or left, "event": event.get("id") or "", "espn_league": event.get("espn_league") or "", "matchup": text},
            "card": _match_card(event.get("title") or "", [event]),
        }
    if found:
        event = sorted(found, key=lambda item: item.get("date") or "")[0]
        return {
            "text": f"That match has not been played. {_event_line(event)}\n\n{_fixture_source(event)}",
            "focus": {"team": item.get("displayName") or left, "event": event.get("id") or "", "espn_league": event.get("espn_league") or "", "matchup": text},
        }
    upcoming = _next_fixture(left)
    if upcoming and other in _plain(upcoming[0]["title"]):
        event, team = upcoming
        return {
            "text": f"That match has not been played. {_event_line(event)}\n\n{_fixture_source(event)}",
            "focus": {"team": team["name"], "event": event.get("id") or "", "espn_league": event.get("espn_league") or "", "matchup": text},
        }
    return {
        "text": f"I couldn't find a listed meeting between {left} and {right}, so I won't invent the score.",
        "focus": {"team": item.get("displayName") or left, "matchup": text},
    }


def _lineup_answer(text, focus):
    focus = focus or {}
    if re.search(r"\b(list of|squad|roster)\b", text, re.IGNORECASE) and not re.search(r"\b(11|eleven|start)", text, re.IGNORECASE):
        return _squad_list(text)
    team_name = _subject(text) or focus.get("team") or ""
    if not team_name and not focus.get("event"):
        return {"text": "Name the team. I won't invent a starting 11."}
    use_saved = bool(re.search(r"\bthat match\b", text, re.IGNORECASE) and focus.get("event") and focus.get("espn_league"))
    if use_saved:
        event = {"id": focus.get("event"), "espn_league": focus.get("espn_league"), "title": "that match", "date": "", "time": "", "venue": "", "league": "", "local": ""}
        team = {"name": focus.get("team") or team_name}
    else:
        found = _next_fixture(team_name) if team_name else None
        if not found:
            return {"text": f"I couldn't find {team_name} on the football schedule, so I won't invent a starting 11."}
        event, team = found
    specific_match = bool(re.search(r"\b(next|tomorrow|that match)\b", text, re.IGNORECASE))
    lines = _starter_lines(event)
    if lines:
        return {
            "text": f"Starting 11 for {event.get('title')} on {event.get('date')}:\n" + "\n".join(lines) + "\n\nSource: ESPN match summary, retrieved for this answer.",
            "focus": {"team": team["name"], "event": event.get("id") or "", "espn_league": event.get("espn_league") or ""},
        }
    if specific_match:
        return {
            "text": f"The starting 11 for {event.get('title')} on {event.get('date')} at {event.get('time') or 'an unlisted time'} Africa/Kampala is not published, so I won't invent the names.",
            "focus": {"team": team["name"], "event": event.get("id") or "", "espn_league": event.get("espn_league") or ""},
        }
    previous = _last_completed(team_name)
    if previous:
        last_event, last_team = previous
        previous_lines = _starter_lines(last_event)
        if previous_lines:
            return {
                "text": (
                    f"The starting 11 for the next match is not published. "
                    f"The last listed match was {_score_line(last_event)}\n"
                    + "\n".join(previous_lines)
                    + "\n\nSource: ESPN match summary, retrieved for this answer."
                ),
                "focus": {"team": last_team["name"], "event": last_event.get("id") or "", "espn_league": last_event.get("espn_league") or ""},
            }
    return {
        "text": f"The starting 11 for {event.get('title')} on {event.get('date')} at {event.get('time') or 'an unlisted time'} Africa/Kampala is not published, so I won't invent the names.",
        "focus": {"team": team["name"], "event": event.get("id") or "", "espn_league": event.get("espn_league") or ""},
    }


def _starter_lines(event):
    league = event.get("espn_league") or ""
    event_id = event.get("id") or ""
    if not league or not event_id:
        return []
    try:
        page = requests.get(
            f"https://site.api.espn.com/apis/site/v2/sports/soccer/{league}/summary",
            params={"event": event_id},
            headers=_HEADERS,
            timeout=12,
        )
        page.raise_for_status()
        rosters = page.json().get("rosters") or []
    except (requests.RequestException, ValueError):
        return []
    lines = []
    for side in rosters:
        starters = [player for player in (side.get("roster") or []) if player.get("starter")]
        label = ((side.get("team") or {}).get("displayName") or side.get("homeAway") or "Team")
        names = [((player.get("athlete") or {}).get("displayName") or "") for player in starters[:11]]
        names = [name for name in names if name]
        if names:
            lines.append(f"{label}: " + ", ".join(names))
    return lines


def _squad_list(text):
    team_name = _subject(text)
    item = _espn_pick(team_name) if team_name else None
    if not item:
        return {"text": f"I couldn't find {team_name or 'that team'} on the football roster, so I won't invent the players."}
    try:
        page = requests.get(
            f"https://site.api.espn.com/apis/site/v2/sports/soccer/{item['league']}/teams/{item['id']}/roster",
            headers=_HEADERS,
            timeout=12,
        )
        page.raise_for_status()
        athletes = page.json().get("athletes") or []
    except (requests.RequestException, ValueError):
        return {"text": f"I couldn't read the squad for {item.get('displayName') or team_name}, so I won't invent the players."}
    names = []
    for athlete in athletes:
        name = athlete.get("displayName") or ""
        position = ((athlete.get("position") or {}).get("abbreviation") or "")
        if name:
            names.append(f"{name} ({position})" if position else name)
    if not names:
        return {"text": f"The roster for {item.get('displayName')} has no players listed, so I won't invent them."}
    shown = item.get("displayName") or team_name
    portrait = _portrait(_team_logo(item), shown, "Team badge")
    result = {
        "text": f"Squad listed for {shown}:\n" + "\n".join(names) + "\n\nSource: ESPN team roster, retrieved for this answer.",
        "focus": {"team": shown, "espn_league": item.get("league") or ""},
    }
    if portrait:
        result["portrait"] = portrait
    return result


def _bind(text, focus, conversation):
    person = focus.get("person") or _person_from_chat(conversation)
    if person and re.search(r"\b(he|him|his)\b", text, re.IGNORECASE):
        text = re.sub(r"\b(he|him|his)\b", person, text, count=1, flags=re.IGNORECASE)
        focus["person"] = person
    team = focus.get("team")
    if team and re.search(r"\b(they|their)\b", text, re.IGNORECASE):
        text = re.sub(r"\b(they|their)\b", team, text, count=1, flags=re.IGNORECASE)
    return text


def _person_from_chat(conversation):
    for item in reversed(conversation or []):
        content = str(item.get("content") or "")
        match = re.search(r"([A-Z][a-zA-Z'’-]+(?: [A-Z][a-zA-Z'’-]+){1,3}) is listed", content)
        if match:
            return match.group(1)
    return ""


def _concept(text):
    lowered = text.lower()
    for pattern, answer in _CONCEPTS:
        if re.search(pattern, lowered):
            return {"text": answer + "\n\nThis explains the rule or the idea. It is not a live result."}
    if re.search(r"which sports are included in the olympic", lowered):
        page = _wiki("Olympic sports", text)
        return page or {"text": "The Olympic programme changes by edition. I could not load the current list, so I won't invent one."}
    return None


def _looks_sports(text):
    return bool(re.search(
        r"\b(football|soccer|rugby|basketball|tennis|boxing|cricket|olympic|afcon|"
        r"world cup|premier league|champions league|nba|ufc|wimbledon|formula|"
        r"fixture|fixtures|offside|goalkeeper|midfielder|ballon|standings|"
        r"match|matches|injured|transfer|referee|var|formation)\b",
        text,
        re.IGNORECASE,
    )) or bool(re.search(r"\b(who is|which club|plays for|next match|what time)\b", text, re.IGNORECASE))


def _playing_answer(text, focus):
    """Yes or no for a named team today or tomorrow, with the kickoff when one is listed."""
    when = "tomorrow" if re.search(r"\btomorrow\b", text, re.IGNORECASE) else ""
    if not when and re.search(r"\btoday\b", text, re.IGNORECASE):
        when = "today"
    named = re.search(r"\b(?:is|are|does|do|will|did)\s+(.+?)\s+play(?:ing)?\b", text, re.IGNORECASE)
    if named and when:
        team_name = _subject(named.group(1)) or named.group(1).strip(" ?.")
    elif named and re.search(r"\bwill\b", text, re.IGNORECASE):
        return _when_answer(named.group(1))
    elif when and re.search(r"\b(?:the match|the game|match tomorrow|game tomorrow|match today|game today)\b", text, re.IGNORECASE):
        team_name = (focus or {}).get("team") or ""
        if not team_name:
            return {"text": "Which team do you mean? I won't guess tomorrow's match."}
    else:
        return None
    found = _next_fixture(team_name)
    if not found:
        return {"text": f"I couldn't find {team_name} on the free football schedule, so I won't say whether they play {when}."}
    event, team = found
    target = datetime.now(_KAMPALA).date()
    if when == "tomorrow":
        target = target + timedelta(days=1)
    news = _matching_news(event, team)
    if event.get("date") == target.isoformat():
        answer = _event_line(event)
        if named:
            answer = f"Yes. {answer}"
    else:
        clock = f" at {event['time']}" if event.get("time") else ""
        local = f" ({event['local']})" if event.get("local") else ""
        league = f", {event['league']}" if event.get("league") else ""
        venue = f", {event['venue']}" if event.get("venue") else ""
        answer = (
            f"No. {team['name']} is not listed to play {when} ({target.isoformat()}, Africa/Kampala). "
            f"Their next match is {event['title']} on {event['date']}{clock}{local}{league}{venue}."
        )
    if news:
        answer += f"\n\nLatest related report ({news['published'][:10]}): {news['headline']} [ESPN]({news['url']})"
    return {"text": f"{answer}\n\n{_fixture_source(event)}", "focus": {"team": team["name"]}}


_AFCON_PAGE = "https://dailysports.net/tournaments/international-africa-cup-of-nations/"
_AFCON_FEED = _AFCON_PAGE + "results-by-ajax/?seasonSlug=2026-2027-5"
_MONTHS = {name: number for number, name in enumerate(
    ["jan", "feb", "mar", "apr", "may", "jun", "jul", "aug", "sep", "oct", "nov", "dec"], 1
)}


def _live_board(text):
    """AFCON fixtures from the free ESPN scoreboard. Sportmonks is not used."""
    today = datetime.now(_KAMPALA).date()
    if re.search(r"\btomorrow\b", text, re.IGNORECASE):
        day = today + timedelta(days=1)
        label = "tomorrow"
    else:
        day = today
        label = "today"
    events = _espn_afcon(day)
    if re.search(r"\blive\b", text, re.IGNORECASE) and not re.search(r"\bmatches\b", text, re.IGNORECASE):
        events = [item for item in events if item.get("live")]
    if not events:
        return {
            "text": (
                f"No Africa Cup of Nations qualifying match is listed for {label} "
                f"({day.isoformat()}, Africa/Kampala).\n\n"
                "Source: [ESPN soccer](https://www.espn.com/soccer/), retrieved for this answer."
            )
        }
    lines = _as_list([_board_line(item) for item in events[:12]])
    return {
        "text": (
            f"Africa Cup of Nations qualifying matches for {label} ({day.isoformat()}):\n"
            + "\n".join(lines)
            + "\n\nSource: [ESPN soccer](https://www.espn.com/soccer/), retrieved for this answer."
        ),
        "card": _match_card(f"AFCON qualifying, {label}", events[:12]),
    }


def _espn_afcon(day):
    return _espn_scoreboard("caf.nations_qual", day)


def _espn_scoreboard(slug, day=None):
    params = {"dates": day.strftime("%Y%m%d")} if day else {}
    try:
        response = requests.get(
            f"https://site.api.espn.com/apis/site/v2/sports/soccer/{slug}/scoreboard",
            params=params,
            headers=_HEADERS,
            timeout=12,
        )
        response.raise_for_status()
        raw_events = response.json().get("events") or []
    except (requests.RequestException, ValueError):
        return []
    listed = []
    for raw in raw_events:
        competition = (raw.get("competitions") or [{}])[0]
        home = next((side for side in competition.get("competitors") or [] if side.get("homeAway") == "home"), {})
        away = next((side for side in competition.get("competitors") or [] if side.get("homeAway") == "away"), {})
        home_name = (home.get("team") or {}).get("displayName") or ""
        away_name = (away.get("team") or {}).get("displayName") or ""
        stamp = (raw.get("date") or "")[:16]
        try:
            kick = datetime.strptime(stamp, "%Y-%m-%dT%H:%M").replace(tzinfo=ZoneInfo("UTC")).astimezone(_KAMPALA)
            date = kick.strftime("%Y-%m-%d")
            clock = kick.strftime("%H:%M")
        except ValueError:
            date, clock = stamp[:10], ""
        status = ((competition.get("status") or {}).get("type") or {}).get("name") or ""
        home_score = home.get("score") if not isinstance(home.get("score"), dict) else (home.get("score") or {}).get("displayValue")
        away_score = away.get("score") if not isinstance(away.get("score"), dict) else (away.get("score") or {}).get("displayValue")
        listed.append({
            "title": f"{home_name} vs {away_name}".strip(),
            "date": date,
            "time": clock,
            "home_score": home_score,
            "away_score": away_score,
            "score": f"{home_score}–{away_score}" if home_score not in (None, "") and away_score not in (None, "") else "",
            "home_logo": (home.get("team") or {}).get("logo") or "",
            "away_logo": (away.get("team") or {}).get("logo") or "",
            "finished": status == "STATUS_FULL_TIME",
            "live": status not in {"", "STATUS_SCHEDULED", "STATUS_FULL_TIME", "STATUS_POSTPONED", "STATUS_CANCELED"},
            "venue": (competition.get("venue") or {}).get("fullName") or "",
        })
    return listed


_COMPETITIONS = (
    (r"premier league|\bepl\b", "eng.1", "English Premier League", "https://www.espn.com/soccer/league/_/name/eng.1"),
    (r"afcon|africa cup|african cup|\bcaf\b|in africa", "caf.nations_qual", "Africa Cup of Nations qualifying", "https://www.espn.com/soccer/league/_/name/caf.nations_qual"),
    (r"champions league", "uefa.champions", "UEFA Champions League", "https://www.espn.com/soccer/league/_/name/uefa.champions"),
    (r"europa league", "uefa.europa", "UEFA Europa League", "https://www.espn.com/soccer/league/_/name/uefa.europa"),
    (r"bundesliga", "ger.1", "Bundesliga", "https://www.espn.com/soccer/league/_/name/ger.1"),
    (r"la liga", "esp.1", "La Liga", "https://www.espn.com/soccer/league/_/name/esp.1"),
    (r"serie a", "ita.1", "Serie A", "https://www.espn.com/soccer/league/_/name/ita.1"),
    (r"ligue 1", "fra.1", "Ligue 1", "https://www.espn.com/soccer/league/_/name/fra.1"),
    (r"nations league", "uefa.nations", "UEFA Nations League", "https://www.espn.com/soccer/league/_/name/uefa.nations"),
)
_NOTABLE = (
    "france", "italy", "belgium", "turkey", "spain", "germany", "england", "portugal",
    "netherlands", "brazil", "argentina", "congo dr", "ivory coast", "senegal",
    "cameroon", "ghana", "nigeria", "morocco", "egypt", "algeria",
)


def _competition_board(text):
    """List a competition's matches, or the headline games when the user asks for the top."""
    if not re.search(r"\b(match|matches|fixture|fixtures|score|scores)\b", text, re.IGNORECASE):
        return None
    found = None
    for pattern, slug, label, source in _COMPETITIONS:
        if re.search(pattern, text, re.IGNORECASE):
            found = (slug, label, source)
            break
    headline = bool(re.search(r"\b(top|best|biggest)\b", text, re.IGNORECASE))
    if found:
        slug, label, source = found
        return _league_board(text, slug, label, source, headline=headline)
    if not headline:
        return None
    today = datetime.now(_KAMPALA).date()
    day = today + timedelta(days=1) if _asked_day(text, today)[1] == "tomorrow" else today
    events = _espn_scoreboard("uefa.nations", day) + _espn_scoreboard("caf.nations_qual", day)
    chosen = _headline_events(events)
    if not chosen:
        return None
    lines = _as_list([_board_line(item) for item in chosen])
    return {
        "text": (
            f"Headline matches for {day.isoformat()} (Africa/Kampala):\n"
            + "\n".join(lines)
            + "\n\nSource: [ESPN soccer](https://www.espn.com/soccer/), retrieved for this answer."
        ),
        "card": _match_card(f"Headline matches, {day.isoformat()}", chosen),
    }


def _headline_events(events):
    ranked = sorted(events, key=_notable_score, reverse=True)
    chosen = [item for item in ranked if _notable_score(item)]
    return (chosen or ranked)[:6]


def _notable_score(event):
    title = (event.get("title") or "").lower()
    return sum(1 for name in _NOTABLE if name in title)


def _asked_day(text, today):
    """Now and today stay on today's date. Tomorrow and 'will be' stay on the next day."""
    later = re.search(r"\btomorrow\b|\bwill be\b|\bgoing to\b", text or "", re.IGNORECASE)
    current = re.search(r"\b(?:now|today|tonight|currently)\b", text or "", re.IGNORECASE)
    if later and not current:
        return today + timedelta(days=1), "tomorrow"
    if current:
        return today, "today"
    return None, "the latest matchweek"


def _league_board(text, slug, label, source, headline=False):
    today = datetime.now(_KAMPALA).date()
    asked, when = _asked_day(text, today)
    events = _espn_scoreboard(slug, asked) if asked else []
    if not asked:
        upcoming = _espn_scoreboard(slug, today + timedelta(days=1))
        if upcoming:
            events = upcoming
            asked = today + timedelta(days=1)
            when = "tomorrow"
        else:
            events = _espn_scoreboard(slug)
    if headline:
        events = _headline_events(events)
    else:
        events = events[:12]
    if asked and not events:
        latest = _espn_scoreboard(slug)
        note = f"No {label} match is listed for {when} ({asked.isoformat()}, Africa/Kampala)."
        if not latest:
            return {"text": note + "\n\nSource: [ESPN soccer](https://www.espn.com/soccer/), retrieved for this answer."}
        lines = [_board_line(item) for item in latest[:8]]
        return {
            "text": (
                note
                + " The latest matchweek on the scoreboard was:\n"
                + "\n".join(lines)
                + "\n\nSource: [ESPN soccer](https://www.espn.com/soccer/), retrieved for this answer."
            )
        }
    if not events:
        return {"text": f"The {label} scoreboard returned no matches.\n\nSource: [ESPN soccer](https://www.espn.com/soccer/), retrieved for this answer."}
    lines = _as_list([_board_line(item) for item in events[:10]])
    heading = f"{label} matches for {when}" if asked else f"{label}, latest scoreboard"
    return {
        "text": heading + ":\n" + "\n".join(lines) + "\n\nSource: [ESPN soccer](https://www.espn.com/soccer/), retrieved for this answer.",
        "card": _match_card(heading, events[:10]),
    }


def _portrait(src, alt, caption):
    src = str(src or "").strip()
    if not src.startswith("http"):
        return None
    return {"src": src, "alt": alt or "", "caption": caption or ""}


def _team_logo(item):
    if not item or not item.get("league") or not item.get("id"):
        return ""
    try:
        page = requests.get(
            f"https://site.api.espn.com/apis/site/v2/sports/soccer/{item['league']}/teams/{item['id']}",
            headers=_HEADERS,
            timeout=12,
        )
        page.raise_for_status()
        logos = ((page.json().get("team") or {}).get("logos") or [])
        return logos[0].get("href") if logos else ""
    except (requests.RequestException, ValueError, IndexError):
        return ""


def _match_card(title, events):
    rows = []
    for item in events:
        home, away = _sides(item.get("title") or "")
        rows.append({
            "home": home,
            "away": away,
            "homeLogo": item.get("home_logo") or "",
            "awayLogo": item.get("away_logo") or "",
            "score": item.get("time") or "vs" if not item.get("finished") and not item.get("live") else (item.get("score") or item.get("time") or "vs"),
            "detail": " · ".join(part for part in (item.get("date"), item.get("venue")) if part),
        })
    return {"title": title, "matches": rows}


def _board_line(item):
    home, away = _sides(item.get("title") or "")
    if item.get("finished") and item.get("home_score") not in (None, ""):
        return _result_phrase(item)[:-1] + (f" at {_hi(item['time'])} Africa/Kampala." if item.get("time") else ".")
    if item.get("live") and item.get("score"):
        return f"{_hi(home)} vs {_hi(away)} is live at {_hi(item['score'])}."
    clock = f" at {_hi(item['time'])} Africa/Kampala" if item.get("time") else ""
    return f"{_hi(home)} vs {_hi(away)} is scheduled for {item.get('date')}{clock}."


def _sportmonks_live():
    token = os.environ.get("SPORTMONKS_TOKEN") or os.environ.get("SPORTMONKS_API_TOKEN")
    if not token:
        return []
    try:
        response = requests.get(
            "https://api.sportmonks.com/v3/football/livescores/inplay",
            params={"api_token": token, "include": "participants;scores;state"},
            headers=_HEADERS,
            timeout=12,
        )
        if response.status_code in {401, 403, 429}:
            return []
        response.raise_for_status()
        payload = response.json().get("data") or []
    except (requests.RequestException, ValueError):
        return []
    matches = []
    for item in payload:
        participants = item.get("participants") or []
        home = next((side.get("name") for side in participants if (side.get("meta") or {}).get("location") == "home"), "")
        away = next((side.get("name") for side in participants if (side.get("meta") or {}).get("location") == "away"), "")
        title = f"{home} vs {away}".strip(" vs") or item.get("name") or "Match"
        goals = []
        for score in item.get("scores") or []:
            if score.get("description") in {"CURRENT", "2ND_HALF", None}:
                value = (score.get("score") or {}).get("goals")
                if value is not None:
                    goals.append(str(value))
        state = ((item.get("state") or {}).get("state") or (item.get("state") or {}).get("name") or "in play")
        matches.append({"title": title, "score": "–".join(goals[:2]) or "no score published", "state": state})
    return matches


def _afcon_matches():
    try:
        response = requests.get(
            _AFCON_FEED,
            headers={
                "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/122.0.0.0 Safari/537.36",
                "X-Requested-With": "XMLHttpRequest",
            },
            timeout=12,
        )
        response.raise_for_status()
        html = (response.json() or {}).get("content") or ""
    except (requests.RequestException, ValueError):
        return []
    matches = []
    for block in html.split("match-item__wrapper")[1:]:
        clock = re.search(r"match-item__time[\s\S]*?>([^<]+)", block)
        teams = re.findall(r'team-name__item text-overflow">([^<]+)', block)
        numbers = re.findall(r">\s*(\d+)\s*<", re.search(r"match-item__scores[\s\S]{0,500}", block).group(0) if re.search(r"match-item__scores", block) else "")
        when = _afcon_when(clock.group(1) if clock else "")
        if len(teams) < 2:
            continue
        matches.append({
            "title": f"{teams[0]} vs {teams[1]}",
            "score": f"{numbers[0]}–{numbers[1]}" if len(numbers) >= 2 else "",
            "when": when[0],
            "day": when[1],
        })
    return matches


def _afcon_when(text):
    found = re.search(r"(\d{1,2})\s+([A-Za-z]{3})\s+(\d{4}),\s*(\d{2}:\d{2})", text or "")
    if not found:
        return text.strip(), None
    day, month, year, clock = found.groups()
    month_number = _MONTHS.get(month.lower())
    if not month_number:
        return text.strip(), None
    try:
        date = datetime(int(year), month_number, int(day)).date()
    except ValueError:
        return text.strip(), None
    return f"{date.isoformat()} at {clock}", date


def _asked_afcon(text):
    return bool(re.search(r"\b(afcon|africa cup|african cup|\bcaf\b)\b", text or "", re.IGNORECASE))


def _afcon_comp(name):
    """True for the Africa Cup of Nations, never for a friendly."""
    text = _plain(name)
    if "friendly" in text or "friendlies" in text:
        return False
    return bool(re.search(r"\b(afcon|africa cup|african cup|caf)\b", text))


def _livescore_answer(text):
    """Quote the score and clock printed on LiveScore. Do not fill in a missing one."""
    names = _live_names(text)
    afcon = _asked_afcon(text)
    events = _livescore_events("https://prod-public-api.livescore.com/v1/api/app/live/soccer/0?locale=en")
    if afcon:
        events = [event for event in events if _afcon_comp(event.get("comp"))]
    if names:
        named = [event for event in events if _names_in(names, event)]
        events = named
        if not events and not afcon:
            events = _pick_team_fixture(_team_events(names))
        elif not events and afcon:
            events = [
                event for event in _pick_team_fixture(_team_events(names))
                if _afcon_comp(event.get("comp"))
            ]
    if not events:
        if re.search(r"\b(afcon|africa cup|african cup|\bcaf\b)\b", text, re.IGNORECASE):
            who = "AFCON"
        else:
            who = " and ".join(names) if names else "right now"
        return {
            "text": (
                f"LiveScore has no football score printed for {who}. I won't invent one.\n\n"
                "Source: [LiveScore](https://www.livescore.com/en/), retrieved for this answer."
            )
        }
    lines = [_livescore_line(event) for event in events[:12]]
    if len(events) == 1 and (events[0].get("time") or "").upper() in {"FT", "AET", "PEN"}:
        lines = [lines[0] + " The match is over, so that is the final score."]
    if len(lines) > 1:
        lines = [f"- {line}" for line in lines]
    result = {
        "text": "\n".join(lines) + "\n\nSource: [LiveScore](https://www.livescore.com/en/), retrieved for this answer."
    }
    if len(events) == 1:
        event = events[0]
        result["focus"] = {
            "kind": "sport",
            "team": names[0] if len(names) == 1 else event["home"],
            "home": event["home"],
            "away": event["away"],
            "eid": event.get("eid") or "",
        }
    return result


def _team_events(names):
    """Recent and upcoming LiveScore rows for these sides, including yesterday's final."""
    today = datetime.now(_KAMPALA).date()
    found = []
    seen = set()
    for offset in range(-2, 4):
        day = (today + timedelta(days=offset)).strftime("%Y%m%d")
        for event in _livescore_events(
            f"https://prod-public-api.livescore.com/v1/api/app/date/soccer/{day}/0?locale=en&MD=1"
        ):
            if not _names_in(names, event) or not event.get("eid") or event["eid"] in seen:
                continue
            seen.add(event["eid"])
            found.append(event)
    return found


def _pick_team_fixture(events):
    """Prefer a match in progress, then the latest final, then the next kickoff."""
    if not events:
        return []
    def clock(event):
        return (event.get("time") or "").upper()
    playing = [event for event in events if clock(event) not in {"", "NS", "FT", "AET", "PEN", "ABD", "POST", "CANC"}]
    if playing:
        return playing[:1]
    finished = [event for event in events if clock(event) in {"FT", "AET", "PEN"}]
    if finished:
        return [max(finished, key=lambda event: event.get("kickoff") or "")]
    waiting = [event for event in events if clock(event) == "NS"]
    return waiting[:1] or events[:1]
    if re.search(r"\bvs\.?\b|\bversus\b|\band\b", text, re.IGNORECASE):
        parts = re.split(r"\s+\bvs\.?\b\s+|\s+\bversus\b\s+|\s+\band\b\s+", text, maxsplit=1, flags=re.IGNORECASE)
        names = [_subject(part) for part in parts]
        return [name for name in names if name and _plain(name) not in {"now", "current"}]
    name = re.sub(r"\b(now|current|currently|afcon|caf)\b", " ", _subject(text), flags=re.IGNORECASE)
    name = re.sub(r"\s+", " ", name).strip()
    if not name or _plain(name) in {"now", "current"}:
        return []
    return [name]


def _live_names(text):
    if re.search(r"\bvs\.?\b|\bversus\b|\band\b", text, re.IGNORECASE):
        parts = re.split(r"\s+\bvs\.?\b\s+|\s+\bversus\b\s+|\s+\band\b\s+", text, maxsplit=1, flags=re.IGNORECASE)
        names = [_subject(part) for part in parts]
        return [name for name in names if name and _plain(name) not in {"now", "current"}]
    name = re.sub(r"\b(now|current|currently|afcon|caf|today|yesterday)\b", " ", _subject(text), flags=re.IGNORECASE)
    name = re.sub(r"\s+", " ", name).strip()
    if not name or _plain(name) in {"now", "current"}:
        return []
    return [name]


def _names_in(names, event):
    title = _plain(f"{event.get('home')} {event.get('away')}")
    words = set(title.split())
    for name in names:
        asked = _plain(_ALIASES.get(_plain(name), name))
        forms = {asked}
        if asked == "dr congo":
            forms.add("congo dr")
        if not any(form and (form in title or set(form.split()) <= words) for form in forms):
            return False
    return True


def _livescore_kickoff(stamp):
    try:
        kick = datetime.strptime(str(stamp)[:14], "%Y%m%d%H%M%S").replace(tzinfo=ZoneInfo("UTC")).astimezone(_KAMPALA)
    except (TypeError, ValueError):
        return ""
    return kick.strftime("%Y-%m-%d at %H:%M Africa/Kampala")


def _livescore_events(url):
    try:
        response = requests.get(
            url,
            headers={**_HEADERS, "Origin": "https://www.livescore.com", "Referer": "https://www.livescore.com/en/"},
            timeout=15,
        )
        response.raise_for_status()
        stages = response.json().get("Stages") or []
    except (requests.RequestException, ValueError):
        return []
    listed = []
    for stage in stages:
        for event in stage.get("Events") or []:
            home = ((event.get("T1") or [{}])[0].get("Nm") or "").strip()
            away = ((event.get("T2") or [{}])[0].get("Nm") or "").strip()
            if not home or not away:
                continue
            listed.append({
                "home": home,
                "away": away,
                "home_score": event.get("Tr1"),
                "away_score": event.get("Tr2"),
                "time": str(event.get("Eps") or "").strip(),
                "kickoff": _livescore_kickoff(event.get("Esd")),
                "eid": str(event.get("Eid") or ""),
                "comp": stage.get("CompN") or stage.get("Cnm") or "",
            })
    return listed


def _scorer_answer(text, focus):
    """Name the players LiveScore lists as scoring, with the printed minute."""
    cleaned = re.sub(r"\b(scored|scorer|scorers|has|have|had)\b", " ", text, flags=re.IGNORECASE)
    names = _live_names(cleaned)
    focus = focus or {}
    saved = None
    if focus.get("eid") and focus.get("home") and focus.get("away"):
        saved = {
            "eid": str(focus["eid"]),
            "home": focus["home"],
            "away": focus["away"],
            "time": "LIVE",
        }
    if not names and focus.get("team"):
        names = [focus["team"]]
    events = []
    if not saved:
        events = _livescore_events("https://prod-public-api.livescore.com/v1/api/app/live/soccer/0?locale=en")
        if names:
            events = [event for event in events if _names_in(names, event)]
    if not events and names:
        events = _pick_team_fixture(_team_events(names))
    if _asked_afcon(text):
        events = [event for event in events if _afcon_comp(event.get("comp"))]
    event = saved or ((events or [None])[0])
    source = "\n\nSource: [LiveScore](https://www.livescore.com/en/), retrieved for this answer."
    if not event or not event.get("eid"):
        who = " and ".join(names) if names else "that match"
        return {"text": f"LiveScore has no match listed for {who}, so I won't invent a scorer.{source}"}
    if (event.get("time") or "").upper() == "NS":
        return {"text": _livescore_line(event) + source, "focus": {"team": names[0] if names else event["home"]}}
    goals = _livescore_goals(event["eid"])
    wanted = ""
    if len(names) == 1 and re.search(r"\bfor\b", text, re.IGNORECASE):
        wanted = names[0]
    if wanted:
        side = 1 if _names_in([wanted], {"home": event["home"], "away": ""}) else 2
        goals = [goal for goal in goals if goal["side"] == side]
    if not goals:
        who = wanted or f"{event['home']} or {event['away']}"
        return {
            "text": f"LiveScore has not listed a goal for {who} in {event['home']} vs {event['away']} yet.{source}",
            "focus": {"team": wanted or event["home"]},
        }
    lines = [
        f"{_hi(goal['name'])} scored for {_hi(event['home'] if goal['side'] == 1 else event['away'])} at {_hi(goal['minute'])}"
        + (" (own goal)" if goal.get("own") else "")
        for goal in goals
    ]
    if len(lines) > 1:
        lines = [f"- {line}" for line in lines]
    return {
        "text": "\n".join(lines) + source,
        "focus": {"team": wanted or event["home"], "event": event["eid"]},
    }


def _livescore_goals(event_id):
    try:
        response = requests.get(
            f"https://prod-public-api.livescore.com/v1/api/app/incidents/soccer/{event_id}?locale=en",
            headers={**_HEADERS, "Origin": "https://www.livescore.com", "Referer": "https://www.livescore.com/en/"},
            timeout=15,
        )
        response.raise_for_status()
        groups = (response.json().get("Incs") or {}).values()
    except (requests.RequestException, ValueError):
        return []
    items = [item for group in groups if isinstance(group, list) for item in group]
    items.sort(key=lambda item: ((item.get("Min") or 0), (item.get("MinEx") or 0)))
    last = [0, 0]
    goals = []
    for item in items:
        score = item.get("Sc")
        if not isinstance(score, list) or len(score) < 2:
            continue
        try:
            current = [int(score[0]), int(score[1])]
        except (TypeError, ValueError):
            continue
        if sum(current) <= sum(last):
            last = current
            continue
        side = 1 if current[0] > last[0] else 2
        minute = str(item.get("Min") or "").strip()
        extra = item.get("MinEx")
        clock = f"{minute}+{extra}" if extra else minute
        if clock.isdigit():
            clock += "'"
        player_side = item.get("Nm")
        goals.append({
            "name": item.get("Pn") or "Unnamed player",
            "minute": clock,
            "side": side,
            "own": player_side not in (None, side),
        })
        last = current
    return goals


def _livescore_line(event):
    home = _hi(event["home"])
    away = _hi(event["away"])
    if (event.get("time") or "").upper() == "NS":
        when = event.get("kickoff") or "a later time"
        return (
            f"{home} vs {away} has not kicked off yet. "
            f"LiveScore lists it for {when}, so there is no live score yet."
        )
    clock = f" {_hi(event['time'])}" if event.get("time") else ""
    if event.get("home_score") not in (None, "") and event.get("away_score") not in (None, ""):
        score = _hi(f"{event['home_score']}-{event['away_score']}")
        return f"{home} {score} {away}{clock}"
    return f"{home} vs {away}{clock}"


def _afcon_line(item):
    score = f" finished {item['score']}" if item.get("score") else " has no score on the page"
    return f"{item['title']}{score} on {item.get('when') or 'an unpublished date'}."


def _yesterday_answer(text):
    """Finished scores from yesterday in Africa/Kampala, for one team or the day's list."""
    day = datetime.now(_KAMPALA).date() - timedelta(days=1)
    stamp = day.strftime("%Y%m%d")
    events = _livescore_events(
        f"https://prod-public-api.livescore.com/v1/api/app/date/soccer/{stamp}/0?locale=en&MD=1"
    )
    names = _live_names(text)
    afcon = _asked_afcon(text)
    source = "\n\nSource: [LiveScore](https://www.livescore.com/en/), retrieved for this answer."
    if afcon:
        events = [event for event in events if _afcon_comp(event.get("comp"))]
    if names:
        matched = [event for event in events if _names_in(names, event)]
        finished = [event for event in matched if (event.get("time") or "").upper() in {"FT", "AET", "PEN"}]
        chosen = finished or matched
        who = " and ".join(names)
        if not chosen:
            return {"text": f"LiveScore has no football match listed for {who} on {day.isoformat()} (Africa/Kampala). I won't invent a score.{source}"}
        event = chosen[0]
        focus = {"kind": "sport", "team": names[0], "home": event.get("home") or "", "away": event.get("away") or "", "eid": event.get("eid") or ""}
        return {"text": f"{_livescore_line(event)} That was yesterday, {day.isoformat()} (Africa/Kampala).{source}", "focus": focus}
    finished = [event for event in events if (event.get("time") or "").upper() in {"FT", "AET", "PEN"}]
    if afcon:
        pool = finished or events
    else:
        africa = [event for event in finished if re.search(r"africa|caf", event.get("comp") or "", re.IGNORECASE)]
        pool = africa or finished or events
    shown = pool[:8]
    if not shown:
        return {"text": f"LiveScore has no football result listed for {day.isoformat()} (Africa/Kampala). I won't invent one.{source}"}
    lines = _as_list([_livescore_line(event) for event in shown])
    extra = f"\n{len(pool) - len(shown)} more finished matches are in the same list." if len(pool) > len(shown) else ""
    return {"text": f"Football results for {day.isoformat()} (Africa/Kampala):\n" + "\n".join(lines) + extra + source}


def _day_answer(text):
    if re.search(r"\blive\b", text, re.IGNORECASE) and re.search(r"\bscore\b", text, re.IGNORECASE):
        live = _livescore_answer(text)
        if live:
            return live
    team = _subject(text)
    general_live = bool(re.search(r"\blive\b", text, re.IGNORECASE)) and not team
    if re.search(r"\b(afcon|africa cup)\b", text, re.IGNORECASE) or general_live:
        board = _live_board(text)
        if board:
            return board
    today = datetime.now(_KAMPALA).date()
    if re.search(r"\btomorrow\b", text, re.IGNORECASE):
        day = today + timedelta(days=1)
        label = "tomorrow"
    elif re.search(r"\bthis week\b", text, re.IGNORECASE):
        return {"text": "I can check a single date in the sports database. Name the day, and I will look up the fixtures. I won't invent a week-long list."}
    elif re.search(r"\bthis month\b", text, re.IGNORECASE):
        return {"text": "I don't have a verified month-long international list, so I won't invent the friendlies."}
    else:
        day = today
        label = "today"
    events = _get("eventsday.php", {"d": day.isoformat(), "s": "Soccer"}).get("events") or []
    if team and re.search(r"\b(live|score)\b", text, re.IGNORECASE):
        named = [item for item in events if team.lower() in (item.get("strEvent") or "").lower()]
        if not named:
            return {
                "text": (
                    f"{team.title()} is not on the football list for {day.isoformat()} (Africa/Kampala), "
                    "so there is no live score to give. I won't invent one."
                )
            }
        event = _event(named[0])
        status = (named[0].get("strStatus") or "").upper()
        if status in {"", "NS"}:
            return {
                "text": (
                    f"{_event_line(event)} It has not kicked off, so there is no live score yet.\n\n"
                    "Source: TheSportsDB events for that date."
                ),
                "focus": {"team": team.title()},
            }
        if event["home"] not in (None, "") and event["away"] not in (None, ""):
            state = "live" if status not in {"FT", "AET", "PEN"} else "finished"
            return {
                "text": (
                    f"{event['title']} is {state}: {event['home']}–{event['away']} "
                    f"({status or 'score published'}).\n\n"
                    "Source: TheSportsDB events for that date."
                ),
                "focus": {"team": team.title()},
            }
        return {
            "text": f"{_event_line(event)} The status is {status or 'unpublished'}, and no score is listed. I won't invent one.",
            "focus": {"team": team.title()},
        }
    if re.search(r"\bafcon\b", text, re.IGNORECASE):
        events = [item for item in events if _afcon_comp(item.get("strLeague"))]
    if re.search(r"\blive\b", text, re.IGNORECASE):
        events = [item for item in events if (item.get("strStatus") or "") not in {"", "NS", "FT", "AET", "PEN", "POST", "CANC"}]
        if not events:
            return {"text": f"No football match is listed as live for {day.isoformat()} in the sports database."}
    if not events:
        return {"text": f"The sports database has no matching football fixture for {label} ({day.isoformat()}, Africa/Kampala). I won't invent one."}
    lines = _as_list([_event_line(_event(item)) for item in events[:8]])
    extra = f" {len(events) - 8} more are in the same list." if len(events) > 8 else ""
    return {"text": f"Football fixtures listed for {day.isoformat()}:\n" + "\n".join(lines) + extra + "\n\nSource: [ESPN soccer](https://www.espn.com/soccer/), retrieved for this answer."}


def _fixture_answer(text):
    name = _subject(text)
    if not name:
        return {"text": "Name the team, and I will look up the fixture. I will not guess a score."}
    team = _team(name)
    if not team:
        return {"text": f"I couldn't find {name} in the sports database, so I won't invent a fixture. " + _directory(text)}
    latest = bool(re.search(r"\b(last|latest|who won|result|final score|yesterday)\b", text, re.IGNORECASE)) and not re.search(
        r"\bnext\b", text, re.IGNORECASE
    )
    event = _last_event(team["id"]) if latest else _next_event(team["id"])
    if not event:
        return {"text": f"The sports database has no {'result' if latest else 'upcoming fixture'} for {team['name']}. I won't invent one. " + _directory(team.get("league") or text)}
    if re.search(r"\btoday\b", text, re.IGNORECASE) and not _is_today(event.get("date")):
        upcoming = event if not latest else _next_event(team["id"])
        extra = f" The next listed match is {upcoming['title']} on {upcoming['date']}." if upcoming else ""
        return {"text": f"{team['name']} has no fixture dated today in Africa/Kampala.{extra}\n\n" + _source_line(upcoming or event, team), "focus": {"team": team["name"]}}
    line = _event_line(event, result=latest)
    return {"text": f"{line}\n\n{_source_line(event, team)}", "focus": {"team": team["name"]}}


def _player_profile(text):
    name = _person_name(text)
    player = _player(name) if name else None
    if not player:
        return None
    born = player.get("dateBorn") or ""
    age = _age(born)
    bits = [f"{player.get('strPlayer') or name} is listed as {player.get('strPosition') or 'a player'}."]
    if player.get("strTeam"):
        bits.append(f"Team listed: {player['strTeam']}.")
    if player.get("strTeam2"):
        bits.append(f"National side listed: {player['strTeam2']}.")
    if player.get("strNationality"):
        bits.append(f"Nationality listed: {player['strNationality']}.")
    if player.get("strBirthLocation"):
        bits.append(f"Birthplace listed: {player['strBirthLocation']}.")
    if age is not None:
        bits.append(f"Age on today's date in Africa/Kampala: {age}, from a birth date of {born}.")
    description = re.sub(r"\s+", " ", player.get("strDescriptionEN") or "").strip()
    if description:
        bits.append(description[:500])
    shown = player.get("strPlayer") or name
    portrait = _portrait(player.get("strCutout") or player.get("strThumb"), shown, player.get("strTeam") or "")
    result = {
        "text": " ".join(bits) + "\n\nSource: TheSportsDB player record, retrieved for this answer.",
        "focus": {"person": shown, "team": player.get("strTeam") or ""},
    }
    if portrait:
        result["portrait"] = portrait
    return result


def _player_club(text):
    name = _person_name(text) or _subject(text)
    player = _player(name) if name else None
    if not player:
        return {"text": f"I couldn't find {name or 'that player'} in the sports database, so I won't invent a club."}
    club = player.get("strTeam") or ""
    shown = player.get("strPlayer") or name
    if not club:
        return {"text": f"The sports database has {shown}, but no current club. I won't invent one.", "focus": {"person": shown}}
    result = {
        "text": f"{shown} is listed with {club}. This record does not separate a club from a national team.\n\nSource: TheSportsDB player record, retrieved for this answer.",
        "focus": {"person": shown, "team": club},
    }
    portrait = _portrait(player.get("strCutout") or player.get("strThumb"), shown, club)
    if portrait:
        result["portrait"] = portrait
    return result


def _career(text):
    profile = _player_profile(text)
    if not profile:
        return {"text": "I couldn't find that career in the sports database, so I won't invent clubs or caps."}
    reply = {"text": profile["text"] + " Former clubs, caps, and trophies are included only when that biography states them.", "focus": profile.get("focus")}
    if profile.get("portrait"):
        reply["portrait"] = profile["portrait"]
    return reply


def _compare(text):
    parts = re.split(r"\s+\band\b\s+|\s+between\s+", text, flags=re.IGNORECASE)
    names = [_person_name(part) or _subject(part) for part in parts]
    names = [name for name in names if name]
    if len(names) < 2:
        return {"text": "Name the two players. I won't decide who is better without the same statistics for both."}
    left, right = _player(names[0]), _player(names[1])
    if not left or not right:
        return {"text": "I couldn't find both players in the sports database, so I won't compare them from memory."}
    return {"text": (
        f"{left.get('strPlayer')}: {left.get('strPosition') or 'position not listed'}, club {left.get('strTeam') or 'not listed'}, nationality {left.get('strNationality') or 'not listed'}. "
        f"{right.get('strPlayer')}: {right.get('strPosition') or 'position not listed'}, club {right.get('strTeam') or 'not listed'}, nationality {right.get('strNationality') or 'not listed'}. "
        "These are the same database fields. They are not a ranking, and they do not say who is better."
        "\n\nSource: TheSportsDB player records, retrieved for this answer."
    )}


def _history(text):
    if not re.search(r"\b(won|hosted|final|history|champion|titles|20\d\d|19\d\d)\b", text, re.IGNORECASE):
        return None
    year = re.search(r"\b(19|20)\d{2}\b", text)
    if re.search(r"\bafcon\b|africa cup", text, re.IGNORECASE) and year:
        term = f"{year.group(0)} Africa Cup of Nations"
    elif re.search(r"world cup", text, re.IGNORECASE) and year:
        term = f"{year.group(0)} FIFA World Cup"
    elif re.search(r"premier league", text, re.IGNORECASE) and year:
        term = f"{year.group(0)}–{int(year.group(0)) + 1} Premier League"
    elif re.search(r"last nba|nba championship", text, re.IGNORECASE):
        term = "NBA Finals"
    elif re.search(r"cricket world cup", text, re.IGNORECASE):
        term = "Cricket World Cup"
    else:
        return None
    fact = _wiki_fact(term)
    if not fact:
        return {"text": f"I couldn't retrieve a page for {term}, so I won't invent the winner or the score."}
    return {"text": fact}


def _named_league(text):
    for pattern, slug, label, _source in _COMPETITIONS:
        if re.search(pattern, text or "", re.IGNORECASE):
            return slug, label
    return None


def _standing_answer(text):
    """A competition table for a standing, or the FIFA place when the question is a ranking."""
    afcon = re.search(r"\b(afcon|caf|africa cup)\b", text, re.IGNORECASE)
    country = _standing_name(text)
    ranking = re.search(r"\bfifa\b|\branking\b", text, re.IGNORECASE)
    if ranking and not afcon:
        return _fifa_rankings(f"ranking of {country}" if country else text)
    league = _named_league(text)
    if league and not (afcon and league[0] != "caf.nations_qual"):
        slug, label = league
        if slug != "caf.nations_qual" or afcon:
            limit = _top_count(text)
            return _slug_standing(slug, label, country, limit)
    if country or afcon:
        return _competition_standing(country, afcon=bool(afcon))
    return None


def _top_count(text):
    found = re.search(r"\btop\s+(\d+)\b|\b(\d+)\s+top\b", text or "", re.IGNORECASE)
    if found:
        return min(int(found.group(1) or found.group(2)), 50)
    if re.search(r"\btop teams\b", text or "", re.IGNORECASE):
        return 10
    return None


def _slug_standing(slug, label, country, limit):
    """The named league's table, on the same board as a country group."""
    try:
        response = requests.get(
            f"https://site.api.espn.com/apis/v2/sports/soccer/{slug}/standings",
            headers=_HEADERS,
            timeout=12,
        )
        response.raise_for_status()
        groups = response.json().get("children") or []
    except (requests.RequestException, ValueError):
        return {"text": f"I couldn't read the {label} table just now, so I won't invent a place."}
    source = "\n\nSource: [ESPN soccer](https://www.espn.com/soccer/), retrieved for this answer."
    item = _espn_pick(country) if country else None
    group = _find_group(groups, country, (item or {}).get("id")) if country else None
    if country and not group:
        return {"text": f"I couldn't find {country} in the {label} table, so I won't invent a place.{source}"}
    if not group:
        group = groups[0] if groups else None
    if not group:
        return {"text": f"The {label} table came back empty, so I won't invent the places.{source}"}
    table = group.get("standings") or {}
    season = table.get("seasonDisplayName") or label
    entries = list(table.get("entries") or [])
    if limit:
        entries = sorted(entries, key=lambda entry: int(_stat(entry, "rank") or 0))[:limit]
        if item:
            wanted = str(item.get("id"))
            if not any(str((entry.get("team") or {}).get("id")) == wanted for entry in entries):
                extra = next(
                    (entry for entry in (table.get("entries") or []) if str((entry.get("team") or {}).get("id")) == wanted),
                    None,
                )
                if extra:
                    entries.append(extra)
    group_name = group.get("name") or label
    if group_name.lower() in {"overall", season.lower(), "league phase"}:
        group_name = label
    return _standing_reply(
        entries,
        group_name,
        season,
        slug,
        country,
        (item or {}).get("id"),
        require_team=bool(country),
    )


def _standing_name(text):
    cleaned = re.sub(
        r"\b(standing|standings|ranking|rankings|fifa|afcon|caf|africa|cup|nations|qualifying|group|table|in|men|women|mens|womens|champions|league|bundesliga|premier|liga|serie|ligue|europa|top|teams)\b",
        " ",
        text,
        flags=re.IGNORECASE,
    )
    return _subject(cleaned)


def _competition_standing(country, afcon=False):
    """The group or league table that contains this country or club."""
    if not country:
        return {"text": "Name the country or team, and I will read its table. I won't invent the places."}
    if afcon or _in_afcon(country):
        table = _afcon_standing(country)
        if table:
            return table
        if afcon:
            return {"text": f"I couldn't find {country} in the AFCON qualifying table, so I won't invent a place.\n\nSource: [ESPN soccer](https://www.espn.com/soccer/), retrieved for this answer."}
    item = _espn_pick(country)
    if not item or not item.get("league"):
        return {"text": f"I couldn't find a league table for {country}, so I won't invent one."}
    return _league_standing(item) or {
        "text": f"I couldn't find {item.get('displayName') or country} in its league table, so I won't invent a place.\n\nSource: [ESPN soccer](https://www.espn.com/soccer/), retrieved for this answer."
    }


def _in_afcon(country):
    return _find_group(_afcon_groups(), country) is not None


def _afcon_groups():
    try:
        response = requests.get(
            "https://site.api.espn.com/apis/v2/sports/soccer/caf.nations_qual/standings",
            headers=_HEADERS,
            timeout=12,
        )
        response.raise_for_status()
        return response.json().get("children") or []
    except (requests.RequestException, ValueError):
        return []


def _find_group(groups, country, team_id=None):
    wanted = str(team_id or "")
    for group in groups:
        table = group.get("standings") or {}
        for entry in table.get("entries") or []:
            team = entry.get("team") or {}
            if wanted and str(team.get("id") or "") == wanted:
                return group
            label = team.get("displayName") or ""
            if _names_in([country], {"home": label, "away": "", "comp": label}):
                return group
    return None


def _afcon_standing(country):
    groups = _afcon_groups()
    if not groups:
        return {"text": "I couldn't read the AFCON qualifying table just now, so I won't invent a place."}
    group = _find_group(groups, country)
    if not group:
        return None
    table = group.get("standings") or {}
    return _standing_reply(
        table.get("entries") or [],
        group.get("name") or "Group",
        table.get("seasonDisplayName") or "Africa Cup of Nations qualifying",
        "caf.nations_qual",
        country,
        afcon=True,
    )


def _league_standing(item):
    league = item.get("league") or ""
    try:
        response = requests.get(
            f"https://site.api.espn.com/apis/v2/sports/soccer/{league}/standings",
            headers=_HEADERS,
            timeout=12,
        )
        response.raise_for_status()
        groups = response.json().get("children") or []
    except (requests.RequestException, ValueError):
        return None
    name = item.get("displayName") or ""
    group = _find_group(groups, name, item.get("id"))
    if not group:
        return None
    table = group.get("standings") or {}
    title = table.get("seasonDisplayName") or group.get("name") or "League table"
    label = group.get("name") or "Table"
    if label.lower() in {"", "overall", title.lower()}:
        label = title
    return _standing_reply(table.get("entries") or [], label, title, league, name, item.get("id"))


def _side_score(side):
    score = side.get("score")
    if isinstance(score, dict):
        score = score.get("displayValue")
        if score in (None, ""):
            score = side.get("score", {}).get("value")
    try:
        return int(float(score))
    except (TypeError, ValueError):
        return None


def _finished_table_matches(league, team_ids, fetch_ids):
    """Finished matches between teams in this table, keyed by match id."""
    found = {}
    for team_id in fetch_ids:
        try:
            response = requests.get(
                f"https://site.api.espn.com/apis/site/v2/sports/soccer/{league}/teams/{team_id}/schedule",
                headers=_HEADERS,
                timeout=12,
            )
            response.raise_for_status()
            events = sorted(response.json().get("events") or [], key=lambda event: event.get("date") or "")
        except (requests.RequestException, ValueError):
            continue
        for event in events:
            competition = ((event.get("competitions") or [None])[0]) or {}
            state = (((competition.get("status") or {}).get("type") or {}).get("state")) or ""
            if state != "post":
                continue
            sides = competition.get("competitors") or []
            parsed = []
            for side in sides:
                side_id = str((side.get("team") or {}).get("id") or "")
                goals = _side_score(side)
                if side_id and goals is not None:
                    parsed.append((side_id, goals))
            if len(parsed) < 2 or not {parsed[0][0], parsed[1][0]} <= team_ids:
                continue
            found[str(event.get("id") or len(found))] = (event.get("date") or "", parsed[0], parsed[1])
    return [found[key] for key in sorted(found, key=lambda key: found[key][0])]


def _add_result(record, scored, conceded):
    record["mp"] += 1
    record["gf"] += scored
    record["ga"] += conceded
    if scored > conceded:
        record["w"] += 1
        record["form"].append("W")
    elif scored == conceded:
        record["d"] += 1
        record["form"].append("D")
    else:
        record["l"] += 1
        record["form"].append("L")


def _catch_up_records(entries, league):
    """Use finished matches the standings table has not counted yet."""
    ids = {str((entry.get("team") or {}).get("id") or "") for entry in entries}
    ids.discard("")
    if not ids:
        return {}
    fetch_ids = ids if len(ids) <= 8 else ids
    if len(ids) > 8:
        return {}
    matches = _finished_table_matches(league, ids, fetch_ids)
    if not matches:
        return {}
    listed = sum(int(_stat(entry, "gamesPlayed") or 0) for entry in entries) / 2
    if len(matches) <= listed:
        return {}
    records = {team_id: {"mp": 0, "w": 0, "d": 0, "l": 0, "gf": 0, "ga": 0, "form": []} for team_id in ids}
    for _date, left, right in matches:
        _add_result(records[left[0]], left[1], right[1])
        _add_result(records[right[0]], right[1], left[1])
    return records


def _standing_reply(entries, group_name, season, league, country, team_key=None, afcon=False, require_team=True):
    group_ids = {str((entry.get("team") or {}).get("id") or "") for entry in entries}
    group_ids.discard("")
    table_matches = _finished_table_matches(league, group_ids, group_ids) if len(group_ids) <= 8 else []
    played_form = {team_id: [] for team_id in group_ids}
    for _date, left, right in table_matches:
        for side, other in ((left, right), (right, left)):
            if side[0] not in played_form:
                continue
            if side[1] > other[1]:
                played_form[side[0]].append("W")
            elif side[1] == other[1]:
                played_form[side[0]].append("D")
            else:
                played_form[side[0]].append("L")
    fresh = _catch_up_records(entries, league)
    rows = []
    asked = None
    for entry in entries:
        team = entry.get("team") or {}
        label = team.get("displayName") or "Unknown"
        if _plain(label) == "congo dr":
            label = "DR Congo"
        team_id = str(team.get("id") or "")
        record = fresh.get(team_id)
        if record:
            goal_diff = record["gf"] - record["ga"]
            cells = [
                str(record["mp"]),
                str(record["w"]),
                str(record["d"]),
                str(record["l"]),
                str(record["gf"]),
                str(record["ga"]),
                _signed(str(goal_diff)),
                str(record["w"] * 3 + record["d"]),
            ]
            order = 0
        else:
            rank = _stat(entry, "rank")
            try:
                order = int(rank)
            except ValueError:
                order = 0
            cells = [
                _stat(entry, "gamesPlayed"),
                _stat(entry, "wins"),
                _stat(entry, "ties"),
                _stat(entry, "losses"),
                _stat(entry, "pointsFor"),
                _stat(entry, "pointsAgainst"),
                _signed(_stat(entry, "pointDifferential")),
                _stat(entry, "points"),
            ]
        row = {
            "rank": _stat(entry, "rank"),
            "team": label,
            "logo": ((team.get("logos") or [{}])[0].get("href")) or "",
            "cells": cells,
            "form": (played_form.get(team_id) or (record["form"] if record else []))[-5:],
            "_id": team_id,
            "_fresh": bool(record),
        }
        rows.append((order, int(cells[7] or 0), int(str(cells[6]).replace("+", "") or 0), int(cells[4] or 0), row))
        if country and ((team_key and team_id == str(team_key)) or _names_in([country], {"home": label, "away": "", "comp": label})):
            row["asked"] = True
            asked = row
    if fresh:
        rows.sort(key=lambda item: (item[1], item[2], item[3]), reverse=True)
        for index, item in enumerate(rows, start=1):
            item[4]["rank"] = str(index)
    else:
        rows.sort(key=lambda item: item[0])
    if not fresh and len(rows) <= 8 and not table_matches:
        for item in rows:
            row = item[4]
            row["form"] = _recent_form(league, row.pop("_id"), group_ids, afcon)
            row.pop("_fresh", None)
    elif not fresh and asked and not table_matches:
        asked["form"] = _recent_form(league, asked.pop("_id"), group_ids, afcon)
        for item in rows:
            item[4].pop("_id", None)
            item[4].pop("_fresh", None)
    else:
        for item in rows:
            item[4].pop("_id", None)
            item[4].pop("_fresh", None)
    if not asked and require_team:
        return None
    place = _ordinal(asked["rank"]) if asked else ""
    where = season if group_name.strip().lower() in season.strip().lower() else f"{group_name} of {season}"
    lines = [item[4] for item in rows]
    source = "\n\nSource: [ESPN soccer](https://www.espn.com/soccer/), retrieved for this answer."
    if asked:
        sentence = f"{_hi(asked['team'])} is {_hi(place)} in {where}."
    else:
        sentence = f"Top {len(lines)} in {where}."
    return {
        "text": f"{sentence}{source}",
        "focus": {"kind": "afcon-standing" if league == "caf.nations_qual" else "standing", "team": asked["team"] if asked else ""},
        "card": {
            "kind": "standing",
            "title": "STANDINGS",
            "group": group_name,
            "rows": lines,
        },
    }


def _ordinal(value):
    try:
        number = int(value)
    except (TypeError, ValueError):
        return str(value or "")
    if 10 <= number % 100 <= 20:
        suffix = "th"
    else:
        suffix = {1: "st", 2: "nd", 3: "rd"}.get(number % 10, "th")
    return f"{number}{suffix}"


def _signed(value):
    text = str(value or "").strip()
    if not text or text.startswith(("+", "-")):
        return text
    try:
        number = int(text)
    except ValueError:
        return text
    if number > 0:
        return f"+{number}"
    return str(number)


def _recent_form(league, team_id, group_ids=None, afcon=False):
    """Results in this table only. An AFCON table ignores friendlies."""
    if not league or not team_id:
        return []
    allowed = {str(item) for item in (group_ids or set()) if item}
    try:
        response = requests.get(
            f"https://site.api.espn.com/apis/site/v2/sports/soccer/{league}/teams/{team_id}/schedule",
            headers=_HEADERS,
            timeout=12,
        )
        response.raise_for_status()
        events = sorted(response.json().get("events") or [], key=lambda event: event.get("date") or "")
    except (requests.RequestException, ValueError):
        return []
    played = []
    for event in events:
        competition = ((event.get("competitions") or [None])[0]) or {}
        state = (((competition.get("status") or {}).get("type") or {}).get("state")) or ""
        if state != "post":
            continue
        label = f"{event.get('name') or ''} {((event.get('season') or {}).get('displayName')) or ''}"
        if afcon and (not _afcon_comp(label) or re.search(r"friendly", label, re.IGNORECASE)):
            continue
        sides = competition.get("competitors") or []
        side_ids = {str((side.get("team") or {}).get("id") or "") for side in sides}
        if allowed and not side_ids <= allowed:
            continue
        mine = next((side for side in sides if str((side.get("team") or {}).get("id")) == str(team_id)), None)
        if not mine:
            continue
        if mine.get("winner") is True:
            played.append("W")
        elif any(side.get("winner") is True for side in sides):
            played.append("L")
        else:
            played.append("D")
    return played[-5:]


def _stat(entry, key):
    for stat in entry.get("stats") or []:
        if stat.get("name") == key or stat.get("abbreviation") == key:
            return stat.get("displayValue") or ""
    return ""


def _fifa_rankings(text):
    count_match = re.search(r"\btop\s+(\d+)\b", text, re.IGNORECASE)
    named = re.search(r"\branking of\s+(.+)$", text, re.IGNORECASE)
    country = named.group(1).strip() if named else ""
    if country and re.search(r"\btop\s+\d+\b", country, re.IGNORECASE):
        country = ""
    count = min(int(count_match.group(1)), 50) if count_match else (200 if country else 10)
    gender = 2 if re.search(r"\bwomen\b", text, re.IGNORECASE) else 1
    try:
        response = requests.get(
            "https://api.fifa.com/api/v3/rankings",
            params={"language": "en", "count": count, "gender": gender},
            headers={**_HEADERS, "Accept": "application/json"},
            timeout=12,
        )
        response.raise_for_status()
        rows = response.json().get("Results") or []
    except (requests.RequestException, ValueError):
        return {"text": "I couldn't read the FIFA rankings just now, so I won't invent the top countries."}
    if not rows:
        return {"text": "The FIFA rankings API returned no teams, so I won't invent the list."}
    published = str(rows[0].get("PubDate") or "")[:10]
    side = "women's" if gender == 2 else "men's"
    if country:
        row = _ranking_row(rows, country)
        if not row:
            return {"text": f"DR Congo is not in the latest FIFA list I could read." if _plain(country) in {"drc", "dr congo"} else f"I couldn't find {country} in the latest FIFA ranking, so I won't invent a place."}
        name, points = _ranking_name(row)
        return {
            "text": (
                f"{name} is {row.get('Rank')} in the {side} world ranking published by FIFA on {published}, with {points} points.\n\n"
                "Source: [FIFA world ranking](https://www.fifa.com/fifa-world-ranking/men), retrieved for this answer."
            ),
            "focus": {"kind": "ranking", "team": name},
        }
    lines = []
    for row in rows[:count]:
        name, points = _ranking_name(row)
        lines.append(f"{row.get('Rank')}. {name} — {points} points")
    return {
        "text": (
            f"Latest {side} world ranking published by FIFA on {published}. "
            "This is the newest list that API returned.\n"
            + "\n".join(lines)
            + "\n\nSource: [FIFA world ranking](https://www.fifa.com/fifa-world-ranking/men), retrieved for this answer."
        ),
        "focus": {"kind": "ranking"},
    }


def _ranking_name(row):
    names = row.get("TeamName") or []
    name = next((item.get("Description") for item in names if item.get("Description")), "Unknown")
    points = row.get("DecimalTotalPoints") or row.get("TotalPoints") or ""
    return name, points


def _ranking_row(rows, country):
    wanted = _plain(_ALIASES.get(_plain(country), country))
    names = {wanted, _plain(country)}
    if wanted in {"dr congo", "drc"} or _plain(country) == "drc":
        names.update({"congo dr", "dr congo", "congo democratic republic"})
    for row in rows:
        label = _plain(_ranking_name(row)[0])
        if label in names:
            return row
    return None


def _no_rumour(text, focus):
    person = focus.get("person") or _person_name(text)
    player = _player(person) if person else None
    current = f" The current club on record is {player.get('strTeam')}." if player and player.get("strTeam") else ""
    return {"text": "I don't have an official transfer announcement for a next club." + current + " Interest and negotiations would be speculation, and I won't present them as a completed move."}


def _wiki_fact(term):
    try:
        response = requests.get(
            "https://en.wikipedia.org/w/api.php",
            params={"action": "query", "prop": "extracts", "explaintext": 1, "titles": term, "format": "json"},
            headers=_HEADERS,
            timeout=12,
        )
        response.raise_for_status()
        pages = (response.json().get("query") or {}).get("pages") or {}
        text = next(iter(pages.values())).get("extract") or ""
    except (requests.RequestException, ValueError, StopIteration):
        return ""
    lowered = text.lower()
    marks = ("won the tournament", "won the final", "in the final", "were the champions", "defeated", "beat ")
    chosen = []
    for sentence in re.split(r"(?<=[.!?])\s+", text):
        sentence_l = sentence.lower()
        if any(mark in sentence_l for mark in marks) and "initially planned" not in sentence_l:
            chosen.append(re.sub(r"\s+", " ", sentence).strip())
        if len(chosen) == 2:
            break
    if not chosen:
        point = -1
        for word in marks:
            found = lowered.find(word)
            if found >= 0 and (point < 0 or found < point):
                point = found
        if point < 0 or not text:
            return ""
        start = text.rfind("\n", 0, point)
        chosen = [re.sub(r"\s+", " ", text[start + 1:point + 220]).strip()]
    window = " ".join(chosen)
    return f"Wikipedia — {term}\n{window}\n\nSource: English Wikipedia, retrieved for this answer."


def _wiki(term, question):
    try:
        from agents.knowledge_agent import wikipedia_summary
    except ImportError:
        return None
    summary = wikipedia_summary(term, question)
    if not summary:
        return None
    return {"text": summary + f"\n\nSource: English Wikipedia, page retrieved for “{term}”."}


def _subject(text):
    cleaned = re.sub(
        r"\b(what|when|who|which|is|are|was|were|will|did|the|next|last|latest|match|result|score|of|for|does|do|play|playing|played|win|won|against|vs|versus|today|tomorrow|yesterday|live|fixture|fixtures|upcoming|club|team|time|his|her|happening|football|soccer|matches|they|starters|starting|start|starts|eleven|lineup|player|players|list|squad|roster|give|me|their)\b",
        " ",
        text,
        flags=re.IGNORECASE,
    )
    words = [word for word in re.findall(r"[A-Za-z0-9&.']+", cleaned) if word.lower() not in _SKIP and not word.isdigit()]
    return " ".join(words[:4]).strip()


def _person_name(text):
    match = re.search(r"\b([A-Z][a-zA-Z'’-]+(?:\s+[A-Z][a-zA-Z'’-]+){1,3})\b", text)
    if match:
        return match.group(1)
    return _subject(text)


def _get(path, params):
    try:
        response = requests.get(f"{_API}/{path}", params=params, headers=_HEADERS, timeout=12)
        response.raise_for_status()
        return response.json() or {}
    except (requests.RequestException, ValueError):
        return {}


def _espn_pick(name):
    query = _ALIASES.get(_plain(name), name)
    try:
        found = requests.get(
            "https://site.web.api.espn.com/apis/common/v3/search",
            params={"query": query, "limit": 5, "type": "team"},
            headers=_HEADERS,
            timeout=12,
        )
        found.raise_for_status()
        items = [
            item for item in (found.json().get("items") or [])
            if item.get("sport") == "soccer" and item.get("id") and item.get("league") and ".w." not in item.get("league")
        ]
    except (requests.RequestException, ValueError):
        return None
    wanted = _plain(query)
    for item in items:
        if wanted == _plain(item.get("displayName") or ""):
            return item
    return items[0] if items else None


def _espn_items(name):
    query = _ALIASES.get(_plain(name), name)
    try:
        found = requests.get(
            "https://site.web.api.espn.com/apis/common/v3/search",
            params={"query": query, "limit": 5, "type": "team"},
            headers=_HEADERS,
            timeout=12,
        )
        found.raise_for_status()
        return [
            item for item in (found.json().get("items") or [])
            if item.get("sport") == "soccer" and item.get("id") and item.get("league") and ".w." not in item.get("league")
        ]
    except (requests.RequestException, ValueError):
        return []


def _world_cup_item(item):
    if not item:
        return None
    return {"id": item.get("id"), "league": "fifa.world", "displayName": item.get("displayName") or ""}


def _espn_schedule(item):
    try:
        page = requests.get(
            f"https://site.api.espn.com/apis/site/v2/sports/soccer/{item['league']}/teams/{item['id']}/schedule",
            headers=_HEADERS,
            timeout=12,
        )
        page.raise_for_status()
        return page.json().get("events") or []
    except (requests.RequestException, ValueError):
        return []


def _read_event(raw, item):
    competition = (raw.get("competitions") or [{}])[0]
    home = next((side for side in competition.get("competitors") or [] if side.get("homeAway") == "home"), {})
    away = next((side for side in competition.get("competitors") or [] if side.get("homeAway") == "away"), {})
    home_name = (home.get("team") or {}).get("displayName") or ""
    away_name = (away.get("team") or {}).get("displayName") or ""
    stamp = (raw.get("date") or "")[:16]
    try:
        kick = datetime.strptime(stamp, "%Y-%m-%dT%H:%M").replace(tzinfo=ZoneInfo("UTC")).astimezone(_KAMPALA)
        date = kick.strftime("%Y-%m-%d")
        clock = kick.strftime("%H:%M")
    except ValueError:
        date, clock = stamp[:10], ""
    status = ((competition.get("status") or {}).get("type") or {}).get("name") or ""
    home_score = _score_value(home.get("score"))
    away_score = _score_value(away.get("score"))
    return {
        "title": f"{home_name} vs {away_name}".strip(),
        "date": date,
        "time": clock,
        "league": item.get("league") or "",
        "venue": (competition.get("venue") or {}).get("fullName") or "",
        "local": "Africa/Kampala" if clock else "",
        "home_score": home_score,
        "away_score": away_score,
        "finished": status == "STATUS_FULL_TIME",
        "score": f"{home_score}–{away_score}" if home_score not in (None, "") and away_score not in (None, "") else "",
        "home_logo": (home.get("team") or {}).get("logo") or "",
        "away_logo": (away.get("team") or {}).get("logo") or "",
        "id": raw.get("id") or "",
        "espn_league": item.get("league") or "",
        "link": f"https://www.espn.com/soccer/team/_/id/{item['id']}",
    }


def _score_value(score):
    if isinstance(score, dict):
        return score.get("displayValue")
    if isinstance(score, list):
        for part in score:
            if isinstance(part, dict) and part.get("displayValue") not in (None, ""):
                return part.get("displayValue")
    if score not in (None, ""):
        return score
    return None


def _last_completed(name):
    finished = []
    seen = set()
    for item in _espn_items(name) + [_world_cup_item(_espn_pick(name))]:
        if not item or not item.get("id") or not item.get("league"):
            continue
        key = (str(item["id"]), item["league"])
        if key in seen:
            continue
        seen.add(key)
        for raw in _espn_schedule(item):
            event = _read_event(raw, item)
            if event.get("finished") and event.get("home_score") not in (None, ""):
                finished.append((event, {"name": item.get("displayName") or name, "league": item.get("league") or ""}))
    if not finished:
        return None
    event, team = max(finished, key=lambda pair: pair[0].get("date") or "")
    return event, team


def _hi(value):
    text = str(value or "").strip()
    return f"⟦{text}⟧" if text else ""


def _as_list(lines):
    if len(lines) > 1:
        return [f"- {line}" for line in lines]
    return lines


def _score_line(event):
    phrase = _result_phrase(event)
    clock = f" at {event['time']} Africa/Kampala" if event.get("time") else ""
    place = f", {event['venue']}" if event.get("venue") else ""
    return f"{phrase[:-1]}{clock}{place}."


def _result_phrase(event):
    home, away = _sides(event.get("title") or "")
    try:
        home_score = int(str(event.get("home_score")).split(".")[0])
        away_score = int(str(event.get("away_score")).split(".")[0])
    except (TypeError, ValueError):
        return f"{event.get('title')} ended on {event.get('date')}."
    when = event.get("date") or "that date"
    if home_score == away_score:
        return f"{_hi(home)} and {_hi(away)} drew {_hi(f'{home_score}–{away_score}')} on {when}."
    if home_score > away_score:
        winner, loser, winner_score, loser_score = home, away, home_score, away_score
    else:
        winner, loser, winner_score, loser_score = away, home, away_score, home_score
    score = _hi(f"{winner_score}–{loser_score}")
    reverse = _hi(f"{loser_score}–{winner_score}")
    patterns = [
        f"{_hi(winner)} defeated {_hi(loser)} {score} on {when}.",
        f"{_hi(loser)} was defeated by {_hi(winner)} {reverse} on {when}.",
        f"{_hi(winner)} won {score} against {_hi(loser)} on {when}.",
        f"{_hi(loser)} lost {reverse} to {_hi(winner)} on {when}.",
    ]
    return random.choice(patterns)


def _sides(title):
    parts = re.split(r"\s+vs\s+", title, maxsplit=1, flags=re.IGNORECASE)
    if len(parts) == 2:
        return parts[0].strip(), parts[1].strip()
    return title, "the opponent"


def _next_fixture(name):
    """Prefer the free ESPN schedule, then TheSportsDB if ESPN has no team."""
    espn = _espn_next(name)
    if espn:
        return espn
    team = _team(_subject(name) or name)
    if not team:
        return None
    event = _next_event(team["id"])
    if not event:
        return None
    return event, team


def _espn_next(name):
    query = _ALIASES.get(_plain(name), name)
    try:
        found = requests.get(
            "https://site.web.api.espn.com/apis/common/v3/search",
            params={"query": query, "limit": 5, "type": "team"},
            headers=_HEADERS,
            timeout=12,
        )
        found.raise_for_status()
        items = [item for item in (found.json().get("items") or []) if item.get("sport") == "soccer" and item.get("league") and item.get("id")]
    except (requests.RequestException, ValueError):
        return None
    if not items:
        return None
    item = items[0]
    try:
        page = requests.get(
            f"https://site.api.espn.com/apis/site/v2/sports/soccer/{item['league']}/teams/{item['id']}",
            headers=_HEADERS,
            timeout=12,
        )
        page.raise_for_status()
        team_body = (page.json().get("team") or {})
        raw = (team_body.get("nextEvent") or [None])[0]
    except (requests.RequestException, ValueError):
        return None
    if not raw:
        return None
    competition = (raw.get("competitions") or [{}])[0]
    names = [((side.get("team") or {}).get("displayName") or "") for side in competition.get("competitors") or []]
    home = next((side for side in competition.get("competitors") or [] if side.get("homeAway") == "home"), {})
    away = next((side for side in competition.get("competitors") or [] if side.get("homeAway") == "away"), {})
    home_name = (home.get("team") or {}).get("displayName") or ""
    away_name = (away.get("team") or {}).get("displayName") or ""
    title = f"{home_name} vs {away_name}".strip()
    stamp = (raw.get("date") or "")[:16]
    try:
        kick = datetime.strptime(stamp, "%Y-%m-%dT%H:%M").replace(tzinfo=ZoneInfo("UTC")).astimezone(_KAMPALA)
        date = kick.strftime("%Y-%m-%d")
        clock = kick.strftime("%H:%M")
        local = kick.strftime("%H:%M Africa/Kampala")
    except ValueError:
        date, clock, local = stamp[:10], "", ""
    league_body = raw.get("league") if isinstance(raw.get("league"), dict) else {}
    league = league_body.get("name") or item.get("league") or ""
    event = {
        "title": title,
        "date": date,
        "time": clock,
        "league": league,
        "home": None,
        "away": None,
        "status": ((competition.get("status") or {}).get("type") or {}).get("state") or "",
        "venue": (competition.get("venue") or {}).get("fullName") or "",
        "local": "Africa/Kampala" if local else "",
        "link": f"https://www.espn.com/soccer/team/_/id/{item['id']}",
        "id": raw.get("id") or "",
        "espn_league": item.get("league") or "",
        "names": [part for part in names if part],
    }
    team = {"name": item.get("displayName") or query, "league": league}
    return event, team


def _matching_news(event, team):
    del event
    names = {_plain(team["name"]), _plain(_ALIASES.get(_plain(team["name"]), ""))}
    names.add("dr congo" if "congo" in _plain(team["name"]) else "")
    names.discard("")
    try:
        page = requests.get(
            "https://site.web.api.espn.com/apis/search/v2",
            params={"query": team["name"], "limit": 3, "type": "article"},
            headers=_HEADERS,
            timeout=12,
        )
        page.raise_for_status()
        results = page.json().get("results") or []
        articles = results[0].get("contents") if results else []
    except (requests.RequestException, ValueError, IndexError):
        return None
    for article in articles or []:
        headline = article.get("displayName") or ""
        if any(name in _plain(headline) for name in names):
            url = ((article.get("link") or {}).get("web") or "")
            if url:
                return {"headline": headline, "published": article.get("date") or "", "url": url}
    return None


def _fixture_source(event):
    return "Source: [ESPN soccer](https://www.espn.com/soccer/), retrieved for this answer."


def _team(name):
    asked = _plain(name)
    name = _ALIASES.get(asked, name)
    for attempt in (name, " ".join(name.split()[:2])):
        teams = _get("searchteams.php", {"t": attempt}).get("teams") or []
        if teams and teams[0].get("idTeam"):
            team = teams[0]
            listed = team.get("strTeam") or attempt
            if asked in _ALIASES or _plain(listed) == asked or asked in _plain(listed):
                return {"id": team["idTeam"], "name": listed, "league": team.get("strLeague") or ""}
    return None


def _plain(value):
    text = unicodedata.normalize("NFKD", value or "")
    return "".join(char for char in text if not unicodedata.combining(char)).lower()


def _player(name):
    players = _get("searchplayers.php", {"p": name}).get("player") or []
    if not players:
        return None
    wanted = _plain(name)
    for player in players:
        if wanted and wanted in _plain(player.get("strPlayer") or ""):
            return player
    return None


def _next_event(team_id):
    events = _get("eventsnext.php", {"id": team_id}).get("events") or []
    return _event(events[0]) if events else None


def _last_event(team_id):
    events = _get("eventslast.php", {"id": team_id}).get("results") or []
    return _event(events[0]) if events else None


def _event(raw):
    timestamp = raw.get("strTimestamp") or ""
    return {
        "title": raw.get("strEvent") or "",
        "date": raw.get("dateEvent") or "",
        "time": (raw.get("strTime") or "")[:5],
        "league": raw.get("strLeague") or "",
        "home": raw.get("intHomeScore"),
        "away": raw.get("intAwayScore"),
        "status": raw.get("strStatus") or "",
        "venue": raw.get("strVenue") or "",
        "local": _kampala_clock(timestamp),
    }


def _event_line(event, result=False):
    when = event["date"] or "an unpublished date"
    home, away = _sides(event.get("title") or "")
    names = f"{_hi(home)} vs {_hi(away)}" if away else _hi(event.get("title"))
    clock = f" at {_hi(event['time'])}" if event.get("time") else ""
    local = f" ({_hi(event['local'])})" if event.get("local") else ""
    league = f", {event['league']}" if event.get("league") else ""
    venue = f", {event['venue']}" if event.get("venue") else ""
    if result and event.get("home") not in (None, "") and event.get("away") not in (None, ""):
        return f"{names} finished {_hi(str(event['home']) + '–' + str(event['away']))} on {when}{league}."
    if result:
        return f"The sports database lists {names} on {when}, but it has no score. I won't invent one."
    return f"{names} is listed for {when}{clock}{local}{league}{venue}."


def _kampala_clock(timestamp):
    try:
        raw = datetime.strptime(timestamp[:19], "%Y-%m-%dT%H:%M:%S").replace(tzinfo=ZoneInfo("UTC"))
    except ValueError:
        return ""
    return raw.astimezone(_KAMPALA).strftime("%H:%M Africa/Kampala")


def _age(date_text):
    try:
        born = datetime.strptime(date_text[:10], "%Y-%m-%d").date()
    except ValueError:
        return None
    today = datetime.now(_KAMPALA).date()
    years = today.year - born.year - ((today.month, today.day) < (born.month, born.day))
    return years if years >= 0 else None


def _is_today(date_text):
    try:
        day = datetime.strptime(date_text, "%Y-%m-%d").date()
    except ValueError:
        return False
    return day == datetime.now(_KAMPALA).date()


def _directory(text):
    lowered = (text or "").lower()
    for mark, label, url in _SPORT_SITE:
        if mark in lowered:
            return f"The official record is kept by [{label}]({url})."
    return "The official record is kept by [FIFA](https://www.fifa.com/) for football and the federation for other sports."


def _source_line(event, team):
    return "Source: TheSportsDB team schedule, retrieved for this answer. " + _directory((event.get("league") or "") + " " + (team.get("league") or ""))
