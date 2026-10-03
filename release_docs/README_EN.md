# StoryEngine Bridge

Optional companion program for the **StoryEngine** Project Zomboid mod (Build 42.20+).
It lets the mod's AI features (radio conversations, AI director, journal, monologue) talk to an AI service
using **your own API key**. Unofficial fan project, not affiliated with The Indie Stone, OpenAI, Anthropic, Google or DeepSeek.

The mod works without the bridge (rule-based events and prepared lines). The bridge only adds AI-written text and decisions.

## Who needs it

- Single player: you.
- Multiplayer: **only the host / server PC**. Players who join only need the mod from the Steam Workshop.

## Install

1. Unzip the folder anywhere (for example `Documents\StoryEngineBridge`).
2. Run `StoryEngineBridge.exe`. The first time, a setup wizard asks for:
   - the AI service: OpenAI, Anthropic (Claude), Google Gemini, DeepSeek, or Test mode (no AI, no cost)
   - your API key (input is hidden; it is saved only in `config.toml` next to the exe)
   - the game data folder (the default `%USERPROFILE%\Zomboid\Lua\StoryEngine` is right for single player and in-game hosting)
3. Leave the window open while you play. The game shows "AI connected" when it sees the bridge.

Run `StoryEngineBridge.exe --setup` to change the settings later, or edit `config.toml` (see `config.example.toml`).

## What is sent, and where

The bridge sends requests **directly from your PC to the AI service you chose** (OpenAI, Anthropic, Google or DeepSeek), under their terms and privacy policies.
Nothing is sent to the mod author or any other server.

Sent: character names and professions, in-game summaries (places, times, kills, injuries, moods, weather, quest events),
radio messages that players type in the mod's radio window (including the open channel), and earlier journal, radio and conversation text for continuity.
Not sent: Steam IDs, account names, IP addresses of other players, or anything outside the game.
Tell the people on your server that their radio messages go to an AI service.

## Cost

AI services bill **you** for the API usage. The bridge limits itself to 120 requests per hour by default
(`[limits] requests_per_hour` in `config.toml`). Check your usage on the service's dashboard.

## Files it touches

Only `Zomboid\Lua\StoryEngine\` (request/response files, heartbeat, journal text files) and its own folder.
It does not modify the game or other programs. To uninstall, close it and delete its folder (this also deletes your saved key).

## Security notes

- `config.toml` contains your API key. Do not share or upload it.
- The exe is built with PyInstaller from the included source code; some antivirus programs flag PyInstaller builds by mistake.
  Compare the SHA256 of the zip with the one published on the download page, or run the Python source yourself.
- AI output can be wrong or unexpected. Prompts keep it in character and in the game world, but it is not reviewed by a human.

## Third-party software

See `THIRD_PARTY_NOTICES.md`.
