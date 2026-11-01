# Yellow.ai AI Automation Intern: Technical Assignments

Two assignments, each in its own folder with its own README and run instructions.

| | Folder | What it is | Stack |
|---|---|---|---|
| 1 | [`assignment-1-lead-sniper`](assignment-1-lead-sniper) | n8n workflow that turns new GitHub stargazers into scored, AI-pitched leads in Discord | n8n, GitHub API, Gemini, Discord webhook |
| 2 | [`assignment-2-weather-delays`](assignment-2-weather-delays) | Async Python script that flags orders delayed by weather | Python 3.10+, asyncio, httpx, OpenWeatherMap |

## Quick start

**Assignment 1:** import `assignment-1-lead-sniper/lead-sniper.workflow.json` into n8n, attach credentials, and follow the setup steps in its README. Unit tests: `cd assignment-1-lead-sniper && npm test`.

**Assignment 2:**

```bash
cd assignment-2-weather-delays
pip install -r requirements.txt
cp .env.example .env            # add your OpenWeatherMap key
python weather_delay_checker.py
pytest -q                       # offline tests
```

Secrets (`.env`, API keys, webhook URLs) are never committed.
