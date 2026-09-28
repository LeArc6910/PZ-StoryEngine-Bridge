# StoryEngine Bridge

Optional companion program for the **StoryEngine** Project Zomboid mod (Build 42.20+).
It connects the mod's AI features — radio conversations and calls from contacts, the open radio channel, AI director, survival journal, character conversations, inner monologue — to an AI service
(OpenAI or Anthropic) using **your own API key**.

Unofficial fan project, not affiliated with The Indie Stone, OpenAI or Anthropic. 한국어 안내: [release_docs/README_KO.md](release_docs/README_KO.md)

- Mod: https://steamcommunity.com/sharedfiles/filedetails/?id=3808950035 (source: https://github.com/skditjdqja12/PZ-StoryEngine)
- Download (Windows): [Releases](https://github.com/skditjdqja12/PZ-StoryEngine-Bridge/releases/latest)

## For players

Download the zip from Releases, unzip it anywhere and run `StoryEngineBridge.exe`. A setup wizard asks for the AI service,
your API key (saved only in `config.toml` next to the exe) and the game data folder. Keep the window open while you play.
In multiplayer only the host / server PC runs the bridge.

Full player guide, including exactly what data is sent: [release_docs/README_EN.md](release_docs/README_EN.md)

## How it works

The game cannot make network requests from Lua, so the mod and the bridge talk through files in `Zomboid/Lua/StoryEngine/`:

```
[Game server Lua] --requests/<id>.json-->  [bridge] --HTTPS--> [AI service]
[Game server Lua] <--responses/<id>.json-- [bridge]
                  <--heartbeat.json------- (connection check)
```

The mod decides all game rules (rewards, trust, quest results); the AI only writes text and picks from whitelisted options,
validated against JSON schemas.

## Run from source

Python 3.11+.

```
pip install -r requirements.txt
python bridge.py            # first run starts the setup wizard (creates config.toml)
python bridge.py --mock     # no AI calls, canned responses
python bridge.py --setup    # redo the setup
python -m unittest discover -s tests
```

`config.toml` holds your key and is git-ignored. See `config.example.toml` for every option (per-module provider/model, hourly request limit).

## Build the Windows release

```
pip install pyinstaller openai anthropic
python build_release.py     # -> ../release/StoryEngineBridge-<version>-win64.zip (+ .sha256)
```

## Files

| Path | Purpose |
|---|---|
| `bridge.py` | main loop, file protocol, rate limit |
| `modules.py` | turns game requests into prompts and JSON schemas (journal, director, radio, radio_scene, banter, monologue, summary) |
| `providers/` | mock, OpenAI (Responses API), Anthropic |
| `prompts/` | system prompts |
| `setup_wizard.py` | first-run setup |
| `release_docs/` | player READMEs shipped in the zip |
