import os

class Config(object):
    # Pyrogram client config
    API_ID = os.environ.get("API_ID", "27240462")
    API_HASH = os.environ.get("API_HASH", "e6d011e39e3e84cad1e417bda13c7dda")
    BOT_TOKEN = os.environ.get("BOT_TOKEN", "7270109001:AAEbVp-jTOvG_C65D1HXQ-i92GkvvKRjJss")
    USER_SESSION = os.environ.get("USER_SESSION", "BQBxIQMAjjIva6RLQ2kS7Ioesl9KoKtiaK8OcSwoPlbukpZMCU-OGvoktgKrkckQAU-HEfDrHoGtSknDxtQeM5KSZpHKM4ei-trWKLk4hfxS1MiEvang991RKMYS9QoDg93CTzvl3w8FpZ3qfdWTWRIp5N8WetCE0QzqPh47B-eyXZqgNXgafnRJwELUXtP7l1ta4g5O0O-t0LloTjdotk0TxY_5L0DL9JpPq95BtZ_lmOpVzxVi3db-TUZqDOeVXHS7YKtkNZllV2ckP4JWkhGEncOuUWbqEiMwywABhWGDstAJwyUUp6iC8a5Ar4GKAUsEgAAJdEk3vOn9YX7zHJyjW58ILgAAAAGpcEk8AA")
    ASSISTANT_ID = int(os.environ.get("ASSISTANT_ID", "7137675580"))

class Txt(object):
    START_TXT = """👋 Welcome to the Music Bot!\n\n
Use these commands to control the bot:\n
/play <song name> - Play a song or add it to the queue\n
/pause - Pause the current song\n
/resume - Resume the paused song\n
/skip - Skip to the next song in the queue\n
/stop - Stop playing and leave the voice chat\n
/queue - Show the current queue\n
/refresh - Recreate the control message with current playback status\n
/seek <seconds> - Skip forward by the specified number of seconds from current position\n\n
You can also use the buttons below the music thumbnail to control playback."""
