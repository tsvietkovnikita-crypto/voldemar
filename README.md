# Voldemar

A Discord music bot with slash commands that plays links from **YouTube, YouTube Music, Spotify and Apple Music** (plus SoundCloud, Bandcamp, Twitch and Vimeo), or anything you search for by name.

- `/play` accepts songs, playlists, albums and artists from all supported services
- A now-playing message with **Pause/Resume, Skip, Stop, Loop and Shuffle** buttons
- Queue management: loop, shuffle, move, remove, skip to a position, go back
- No Spotify or Apple Music account or API key needed
- Leaves the voice channel by itself when the queue is done or everyone has left

It's built for running on your own Windows PC for your own servers. See [Good to know](#good-to-know) for the limits that come with that.

## How it works

```
Discord ◄── slash commands, buttons ──► Voldemar (Python: discord.py + wavelink)
   ▲                                         │ localhost:2333
   │ voice (end-to-end encrypted)            ▼
   └──────────────────────────────── Lavalink (Java audio server, started by the bot)
                                        ├─ youtube-plugin → YouTube / YouTube Music
                                        └─ LavaSrc        → Apple Music (matched on YouTube by ISRC)
Spotify: the bot reads the song list from Spotify's public embed page, then plays each song
from YouTube Music, looking it up just before it plays.
```

Spotify and Apple Music don't allow streaming their audio to Discord, so every song is played from YouTube. For Apple Music the exact recording is found by its ISRC code; for Spotify by artist, title and duration.

## Setup

You need Windows 10 or 11 and a Discord account with permission to add bots to your server.

### 1. Install the tools

Open PowerShell and run:

```powershell
winget install astral-sh.uv
winget install EclipseAdoptium.Temurin.21.JRE
```

`uv` installs Python and the bot's libraries for you. Java 17 or newer is needed for Lavalink. An older Java (such as Java 8) can stay installed; the bot finds the right one. Open a new terminal afterwards so both commands are on your PATH.

### 2. Create the Discord bot

1. Open the [Discord Developer Portal](https://discord.com/developers/applications) and click **New Application**. Name it (e.g. "Voldemar").
2. Go to **Bot**, click **Reset Token** and copy the token. Treat it like a password.
3. No privileged intents are needed; leave them all off.

### 3. Configure

In the project folder:

```powershell
copy .env.example .env
notepad .env
```

- Paste the token after `DISCORD_TOKEN=`.
- Recommended: put your server's ID in `GUILD_IDS` so commands appear instantly. To get the ID, enable *Settings → Advanced → Developer Mode* in Discord, then right-click your server and choose *Copy Server ID*.

Every other setting has a working default (see [Configuration](#configuration)).

### 4. Run

```powershell
uv run voldemar
```

The first start downloads Python packages, Lavalink (about 100 MB) and its plugins. Later starts take a few seconds. The console then shows an **invite link**. Open it, pick your server and confirm; it asks for exactly these permissions: View Channel, Send Messages, Embed Links, Connect and Speak.

Join a voice channel and try `/play never gonna give you up`. Press **Ctrl+C** to stop the bot; it stops Lavalink too.

## Commands

| Command | What it does |
|---|---|
| `/play query` | Play or queue a link or search. Joins your voice channel |
| `/pause` · `/resume` | Pause and continue |
| `/skip [to]` | Skip the current song, or jump to a queue position |
| `/previous` | Play the previous song again |
| `/stop` | Stop, clear the queue and leave |
| `/seek position` | Jump within the song: `1:23`, `83` or `1m23s` |
| `/volume [level]` | Show or set the volume (0–150, 100 is normal) |
| `/queue [page]` | Show the queue |
| `/nowplaying` | Show the current song with a progress bar |
| `/loop mode` | Repeat off, the current song, or the whole queue |
| `/shuffle` · `/clear` | Shuffle or empty the upcoming songs |
| `/remove position` · `/move from to` | Edit the queue |
| `/help` | List the commands |

Everyone can use the commands, but only from the voice channel the bot is in. The bot moves to another channel only when it's idle or alone. Errors are shown only to the person who ran the command.

## Supported links

| Service | Works with |
|---|---|
| YouTube | Videos, Shorts, playlists. A video opened from a playlist or mix plays just that video; use the playlist link (`youtube.com/playlist?list=…`) to queue all of it |
| YouTube Music | Songs and playlists. For albums, use the album's ⋮ → Share link (album page URLs can't be opened) |
| Spotify | Songs, albums, playlists (the first 100 songs), artists (top 10), `spotify.link` share links |
| Apple Music | Songs, albums, playlists, artists |
| Others | SoundCloud, Bandcamp, Twitch, Vimeo |
| Anything else | Searched on YouTube Music |

Direct links to audio files (`https://…/song.mp3`) are off by default: they would let anyone in your server make your PC fetch any URL, including devices on your home network, and would show your IP address to that site. Set `ALLOW_DIRECT_LINKS=true` to allow them anyway.

## Configuration

All settings live in `.env`:

| Setting | Default | Meaning |
|---|---|---|
| `DISCORD_TOKEN` | — | Bot token (required) |
| `GUILD_IDS` | empty | Server IDs, comma-separated, for instant command updates. Empty means commands are registered globally |
| `DEFAULT_VOLUME` | `80` | Starting volume |
| `MAX_QUEUE_SIZE` | `500` | Maximum number of queued songs |
| `IDLE_TIMEOUT` | `180` | Seconds before leaving when nothing plays |
| `EMPTY_CHANNEL_TIMEOUT` | `60` | Seconds before leaving an empty channel |
| `ALLOW_DIRECT_LINKS` | `false` | Allow direct audio file links (see above) |
| `LAVALINK_PASSWORD` | `youshallnotpass` | Password between the bot and Lavalink |
| `LAVALINK_HOST` / `LAVALINK_PORT` | `127.0.0.1` / `2333` | Where Lavalink listens |
| `LAVALINK_AUTOSTART` | `true` | Start Lavalink with the bot. Set to `false` if you run it yourself |
| `JAVA_PATH` | empty | Path to `java.exe`, if Java 17+ isn't found automatically |
| `APPLE_MUSIC_COUNTRY` | `US` | Apple Music storefront for searches |
| `APPLE_MUSIC_MEDIA_TOKEN` | empty | Only if the automatic Apple Music token stops working (see below) |
| `YOUTUBE_OAUTH_ENABLED` / `YOUTUBE_OAUTH_REFRESH_TOKEN` | `false` / empty | YouTube sign-in (see below) |

## Troubleshooting

Logs are in `logs/voldemar.log` (the bot) and `logs/lavalink.log` (the audio server).

**Slash commands don't show up.** Set `GUILD_IDS` and restart the bot; without it, global commands can take a while. Make sure the bot was invited with the link it prints (it includes the `applications.commands` scope), then reload Discord with Ctrl+R.

**"The music server isn't connected yet."** Lavalink is still starting, or it failed. Check `logs/lavalink.log`. A common cause is another program using port 2333; change `LAVALINK_PORT`.

**YouTube songs fail, or "Sign in to confirm you're not a bot".** YouTube changes things regularly. Try these in order:

1. Update the YouTube plugin: set the newest version from [youtube-source releases](https://github.com/lavalink-devs/youtube-source/releases) in `lavalink/application.yml` (`dev.lavalink.youtube:youtube-plugin:X.Y.Z`) and restart. Lavalink downloads it by itself.
2. Sign in with a **spare** Google account (never your main one; the account can be restricted):
   1. Set `YOUTUBE_OAUTH_ENABLED=true` in `.env`.
   2. Run `uv run voldemar-lavalink`. The console shows a code: open https://www.google.com/device, enter it and pick the spare account.
   3. Lavalink then prints a refresh token. Put it in `.env` as `YOUTUBE_OAUTH_REFRESH_TOKEN`, stop it with Ctrl+C and start the bot as usual.
3. If errors mention the signature cipher, run [yt-cipher](https://github.com/kikkia/yt-cipher) and fill in the commented `remoteCipher` block in `lavalink/application.yml`.

**Apple Music links stopped working.** The access token is normally fetched from music.apple.com automatically. If that fails, get one by hand: open https://music.apple.com in a browser, open DevTools → Sources, and search all `index-*.js` files for a long string starting with `eyJ`. Put it in `.env` as `APPLE_MUSIC_MEDIA_TOKEN`.

**Spotify links stopped working.** The bot reads Spotify's public embed page. If Spotify changes that page, `src/voldemar/music/spotify.py` needs an update; the tests in `tests/test_spotify.py` show what the parser expects.

**The bot joins but stays silent.** Check that it has the **Speak** permission in that channel and isn't server-muted. Discord requires end-to-end encrypted voice (DAVE) since March 2026; Lavalink 4.2.2 (downloaded automatically) supports it, while older Lavalink versions won't work.

## Good to know

- **Private use only.** YouTube's and Spotify's terms don't allow streaming their content through bots at scale. That's why big public music bots like Rythm and Groovy were shut down. Keep Voldemar in your own servers.
- The bot is only online while this PC is on and running it.
- Spotify matches are found by artist, title and duration. Rarely, a different version of a song gets picked.

## Development

```powershell
uv run pytest        # unit tests
uv run ruff check .  # lint
uv run ruff format . # format
```

Project layout:

```
lavalink/application.yml      Lavalink and plugin configuration
src/voldemar/
  __main__.py                 entry point: starts Lavalink, then the bot
  bot.py                      Discord client, Lavalink connection, command registration
  config.py                   settings from .env
  lavalink_server.py          finds Java, downloads and runs Lavalink
  cogs/music.py               slash commands
  cogs/events.py              Lavalink events, leaving empty channels
  music/queue.py              the queue (loop modes, history, reordering)
  music/sources.py            recognising and cleaning up links
  music/spotify.py            Spotify embed page reader
  music/resolver.py           loading tracks, matching Spotify songs on YouTube Music
  music/player.py             per-server playback
  music/guards.py             voice channel and permission checks
  ui/                         now-playing panel, buttons and text formatting
tests/                        unit tests and Spotify page fixtures
```
