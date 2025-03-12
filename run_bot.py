#!/usr/bin/env python3
"""
Run script for the Telegram Music Bot
This script helps run the bot from the project root directory
"""

import os
import sys
import time

# Add the current directory to the path so imports work correctly
sys.path.insert(0, os.path.abspath(os.path.dirname(__file__)))

# Import and run the bot
from spotify_bot.bot import MusicBot

if __name__ == "__main__":
    print("Starting Music Bot...")
    bot = MusicBot()
    bot.run() 