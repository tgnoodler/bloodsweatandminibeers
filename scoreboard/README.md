# The cloud Scoreboard

Everything in this folder runs on GitHub, with no home computer involved. It exists because the regular build's
Scoreboard (`sunday.html`) and Rundown (`wire.json`) did not move on to the new week, and the regular build rewrites
those two files on every run, so they cannot be fixed in place from here.

## What it makes

| File | What it is | Written by |
| --- | --- | --- |
| `/scoreboard.html` | The Scoreboard page for the current week | `build.py` |
| `/index.html` (its scoreboard only) | Kept on the same week, in place | `build.py` |
| `scoreboard/week.json` | The week's matchups, lineups, projections, kickoffs | `build.py` |
| `scoreboard/wire.json` | The Rundown: touchdowns, zeros, Ices, lead changes | `live.py` |
| `scoreboard/status.json` | Ice count and warnings for the page's top bar | `live.py` |
| `scoreboard/state.json` | The engine's memory between runs | `live.py` |
| `scoreboard/latest.json` | Whether the weekly report picture is ready | `build.py` |
| `/report.html` | The Weekly Report page, on the newest card | `report.py` |
| `recap/wkN.html`, `.png` | The week's report card, if the home build has not drawn it five hours after the last kickoff | `report.py` |
| `/sw.js` | Sends `/sunday.html` visitors to `/scoreboard.html`, and `/recap.html` to `/report.html` | by hand |

## How it runs

- **Scoreboard week** (`.github/workflows/scoreboard-week.yml`, twice an hour) runs `build.py`. It moves the page to
  the new week 12 hours before the first kickoff, refreshes it when rosters or kickoff times change, and keeps every
  Scoreboard link on the site pointed at `scoreboard.html`.
- **Scoreboard live** (`.github/workflows/scoreboard-live.yml`, every ten minutes) runs `live.py`. With a game on or
  within 75 minutes it stays up for the whole window, reading Sleeper every 20 seconds and committing the Rundown as
  things happen. Otherwise it makes one pass, to catch stat corrections, and stops.

`report.py` is called by `build.py`; it needs Chrome, which GitHub's runners have, to take the card's picture.

`engine.py` holds the rules and makes no network calls. `test_engine.py` replays a made-up game day through it:
`python3 scoreboard/test_engine.py`.

## The rules the engine applies

- **Touchdown:** a starter's touchdown count goes up in Sleeper's stats. Tags: 40+ yards, first score of the game
  (Sleeper's own flag), first of the week, hat trick / grand slam / fistful (3 / 4 / 5 by one player), vulture (a
  back who is not his team's lead rusher in that game), off the schneid (an owner's first of the week, in the 4th
  quarter), garbage time (4th quarter, 22 or more apart).
- **Zeros:** a starter at zero or below goes on the radar late in the 1st quarter (7:30 left). Ice watch at the
  start of the 3rd, Warning at the start of the 4th, Off zero when he scores, Ice averted if that was after a warning.
- **Iced:** zero or below 90 seconds after his game goes final. A starter on a bye counts from the week's first
  kickoff, an empty slot from the last. A lineup change withdraws it; a later stat correction overturns it.
- **Injury:** a starter at zero whom Sleeper lists as Out, Doubtful or on IR during his game.
- **Lead change:** the lead passes from one owner to the other. If the owner passed has nobody left, it is final.
- **Swing:** the 60 percent favorite changes without a lead change.

## Joining this up with the home build

The page reads three files from this folder (`wire.json`, `status.json`, `latest.json`). To hand the Scoreboard back
to the home build once its week rollover is fixed: stop both workflows, delete the fetch handler in `/sw.js` (leave
the file, so browsers pick up the change), and point the nav links back at `sunday.html`. To go the other way and
retire the home build's Scoreboard, have it stop writing `sunday.html` and `wire.json`.
