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
| `LAVALINK_PROFILE` | empty | `cloud` on a cloud server: uses `lavalink/application-cloud.yml` (see below) |
| `YOUTUBE_CIPHER_URL` / `YOUTUBE_CIPHER_TOKEN` | empty | A [yt-cipher](https://github.com/kikkia/yt-cipher) server for YouTube signatures (set up for you on a cloud server) |

## Run it 24/7 on Oracle Cloud (free)

On your PC the bot is only online while the PC is on and the window is open. Oracle Cloud's **Always Free** tier gives you a small server that runs it around the clock, for free. On that server the bot restarts by itself after a crash or a reboot.

### 1. Create the server (in your browser)

1. **Sign up** at https://signup.cloud.oracle.com.
   - A bank card is asked for identity verification only; Always Free resources aren't charged.
   - The **home region can't be changed later**. In Europe, avoid Frankfurt, which often runs out of free ARM servers; Amsterdam, Stockholm, Milan or Marseille work well.
2. In the console, open **Compute → Instances → Create instance**:
   - **Name:** `voldemar`
   - **Image:** click *Edit* next to "Image and shape", *Change image*, **Canonical Ubuntu 24.04**.
   - **Shape:** *Change shape*, **Ampere**, **VM.Standard.A1.Flex**, then set **1 OCPU and 4 GB memory**. It's marked "Always Free-eligible".
     - Keep it at 4 GB: Oracle reclaims free servers that stay under 20% memory use for a week, and the bot uses about 1.3 GB.
   - **Networking:** keep the defaults, with *Assign a public IPv4 address* on. Don't open any extra ports; the bot only makes outgoing connections.
   - **SSH keys:** choose *Paste public keys* and paste the public key (see step 2).
   - Click **Create**. If it says "Out of capacity", free ARM servers are sold out right now; see below.
3. When the instance shows **Running**, copy its **Public IP address**.

**"Out of capacity"?** Oracle only frees up ARM servers now and then, and single-zone regions like Stockholm can't switch zones. Let a script keep trying for you:

1. Create an API key on your PC and upload its public half: *profile icon → My profile → API keys → Add API key → Paste a public key*.
   ```powershell
   mkdir $HOME\.oci -Force
   openssl genrsa -out $HOME\.oci\voldemar_api_key.pem 2048
   openssl rsa -pubout -in $HOME\.oci\voldemar_api_key.pem -out $HOME\.oci\voldemar_api_key_public.pem
   ```
   (`openssl` comes with Git for Windows.)
2. Paste the "Configuration file preview" Oracle shows into `$HOME\.oci\config`, with `key_file=~/.oci/voldemar_api_key.pem`.
3. Run the script and leave the PC on:
   ```powershell
   uv run --script deploy/oracle-create-instance.py
   ```
   It retries every couple of minutes, which can take hours or a day or two. It creates the server with the settings above, prints its IP, and never creates a second one.

### 2. Install the bot on it (from your PC)

Create an SSH key once on your PC, and paste the contents of the `.pub` file in step 1:

```powershell
ssh-keygen -t ed25519 -f $HOME\.ssh\voldemar_oracle -C voldemar
Get-Content $HOME\.ssh\voldemar_oracle.pub
```

Then, with `<IP>` being the server's address:

```powershell
ssh -i $HOME\.ssh\voldemar_oracle ubuntu@<IP> "curl -fsSL https://raw.githubusercontent.com/tsvietkovnikita-crypto/voldemar/main/deploy/setup-server.sh -o setup-server.sh && sudo bash setup-server.sh --no-start"
scp -i $HOME\.ssh\voldemar_oracle .env ubuntu@<IP>:/tmp/voldemar.env
ssh -i $HOME\.ssh\voldemar_oracle ubuntu@<IP> "sudo install -o voldemar -g voldemar -m 600 /tmp/voldemar.env /home/voldemar/voldemar/.env && rm /tmp/voldemar.env"
```

Check that the server can actually play music before going live:

```powershell
ssh -i $HOME\.ssh\voldemar_oracle ubuntu@<IP> "sudo -u voldemar -H bash -c 'cd ~/voldemar && .venv/bin/voldemar-check'"
```

If every source says `ok`, start it with `sudo systemctl restart voldemar` (run over `ssh` as above). **Then stop the bot on your PC.** Two copies with the same token would both answer every command.

### 3. If YouTube fails on the server

YouTube blocks data-center IPs much harder than home connections, so on most cloud servers `voldemar-check` shows YouTube (and therefore Spotify and search) as `FAILED`. The fix is a signed-in YouTube client plus a signature-decoding helper. Run these on the server (`ssh -i $HOME\.ssh\voldemar_oracle ubuntu@<IP>`):

1. Install the helper, which also points the bot's `.env` at it:
   ```bash
   sudo bash /home/voldemar/voldemar/deploy/setup-server.sh --with-cipher --no-start
   ```
2. In `/home/voldemar/voldemar/.env` (edit with `sudo -u voldemar nano /home/voldemar/voldemar/.env`), set:
   ```
   LAVALINK_PROFILE=cloud
   YOUTUBE_OAUTH_ENABLED=true
   ```
3. Sign in with a **spare Google account, never your main one**; accounts used this way can get restricted.
   1. Run:
      ```bash
      sudo systemctl stop voldemar
      sudo -u voldemar -H bash -c 'cd ~/voldemar && .venv/bin/voldemar-lavalink'
      ```
   2. It prints a code. Open https://www.google.com/device on any device, enter the code and pick the spare account.
   3. Lavalink then prints a **refresh token**. Put it in `.env` as `YOUTUBE_OAUTH_REFRESH_TOKEN` and press Ctrl+C.
4. Run `voldemar-check` again (as in step 2). When everything says `ok`, run `sudo systemctl restart voldemar`.

### Day to day

All of these are run on the server over `ssh`:

| Task | Command |
|---|---|
| Live log | `journalctl -u voldemar -f` |
| Is it running? | `systemctl status voldemar` |
| Restart / stop | `sudo systemctl restart voldemar` / `sudo systemctl stop voldemar` |
| Update to the newest code | `sudo bash /home/voldemar/voldemar/deploy/update.sh` |
| Test playback | `sudo -u voldemar -H bash -c 'cd ~/voldemar && .venv/bin/voldemar-check'` |

Keep a copy of your `.env` on your PC. If Oracle ever reclaims or deletes the server, create a new one and repeat step 2.

## Troubleshooting

Logs are in `logs/voldemar.log` (the bot) and `logs/lavalink.log` (the audio server). On the Oracle server, also check `journalctl -u voldemar`.

**Songs don't play: is it the bot, or the music source?** Run `uv run voldemar-check` (on the server, see [Day to day](#day-to-day)). It plays a test link from every source without Discord and shows which ones work, while any running bot is left alone.

**Slash commands don't show up.** Set `GUILD_IDS` and restart the bot; without it, global commands can take a while. Make sure the bot was invited with the link it prints (it includes the `applications.commands` scope), then reload Discord with Ctrl+R.

**"The music server isn't connected yet."** Lavalink is still starting, or it failed. Check `logs/lavalink.log`. A common cause is another program using port 2333; change `LAVALINK_PORT`.

**YouTube songs fail, or "Sign in to confirm you're not a bot".** YouTube changes things regularly. Try these in order:

1. Update the YouTube plugin in `lavalink/application.yml` and restart; Lavalink downloads it by itself. It's currently pinned to a development build, because release 1.18.2 can no longer stream most videos. Once a release newer than 1.18.2 appears on [youtube-source releases](https://github.com/lavalink-devs/youtube-source/releases), switch to it (`dev.lavalink.youtube:youtube-plugin:X.Y.Z` with `snapshot: false`). The comments above `clients:` in the same file explain which YouTube clients currently work for what.
2. Sign in with a **spare** Google account (never your main one; the account can be restricted):
   1. Set `YOUTUBE_OAUTH_ENABLED=true` in `.env`.
   2. Run `uv run voldemar-lavalink`. The console shows a code: open https://www.google.com/device, enter it and pick the spare account.
   3. Lavalink then prints a refresh token. Put it in `.env` as `YOUTUBE_OAUTH_REFRESH_TOKEN`, stop it with Ctrl+C and start the bot as usual.
3. If errors mention the signature cipher ("sig function"), run [yt-cipher](https://github.com/kikkia/yt-cipher) and set `YOUTUBE_CIPHER_URL` and `YOUTUBE_CIPHER_TOKEN` in `.env`. On an Oracle server, `setup-server.sh --with-cipher` does all of that for you.

**Apple Music links stopped working.** The access token is normally fetched from music.apple.com automatically. If that fails, get one by hand: open https://music.apple.com in a browser, open DevTools → Sources, and search all `index-*.js` files for a long string starting with `eyJ`. Put it in `.env` as `APPLE_MUSIC_MEDIA_TOKEN`.

**Spotify links stopped working.** The bot reads Spotify's public embed page. If Spotify changes that page, `src/voldemar/music/spotify.py` needs an update; the tests in `tests/test_spotify.py` show what the parser expects.

**The bot joins but stays silent.** Check that it has the **Speak** permission in that channel and isn't server-muted. Discord requires end-to-end encrypted voice (DAVE) since March 2026; Lavalink 4.2.2 (downloaded automatically) supports it, while older Lavalink versions won't work.

## Good to know

- **Private use only.** YouTube's and Spotify's terms don't allow streaming their content through bots at scale. That's why big public music bots like Rythm and Groovy were shut down. Keep Voldemar in your own servers.
- On your PC, the bot is only online while the PC is on and running it. For 24/7, see [Run it 24/7 on Oracle Cloud](#run-it-247-on-oracle-cloud-free).
- Spotify matches are found by artist, title and duration. Rarely, a different version of a song gets picked.

## Development

```powershell
uv run pytest          # unit tests
uv run ruff check .    # lint
uv run ruff format .   # format
uv run voldemar-check  # can every source actually play right now?
```

Project layout:

```
lavalink/application.yml      Lavalink and plugin configuration
lavalink/application-cloud.yml   YouTube setup for cloud servers (LAVALINK_PROFILE=cloud)
deploy/                       Oracle/Linux server: setup and update scripts, systemd services
src/voldemar/
  __main__.py                 entry point: starts Lavalink, then the bot
  check.py                    voldemar-check: playback test without Discord
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
