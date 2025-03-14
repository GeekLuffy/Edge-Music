import os
import aiohttp
import asyncio
from PIL import Image
from io import BytesIO
import time
import re
from pyrogram.types import InlineKeyboardButton, InlineKeyboardMarkup

# Function to download thumbnail from YouTube
async def download_thumbnail(video_id):
    thumbnail_url = f"https://img.youtube.com/vi/{video_id}/maxresdefault.jpg"
    hq_thumbnail_url = f"https://img.youtube.com/vi/{video_id}/hqdefault.jpg"

    os.makedirs("thumbnails", exist_ok=True)

    thumbnail_path = f"thumbnails/{video_id}.jpg"

    if os.path.exists(thumbnail_path):
        return thumbnail_path
    
    # Download the thumbnail
    async with aiohttp.ClientSession() as session:
        try:
            # Try to download maxresdefault first
            async with session.get(thumbnail_url) as response:
                if response.status == 200:
                    data = await response.read()
                    # Save the thumbnail
                    with open(thumbnail_path, "wb") as f:
                        f.write(data)
                    return thumbnail_path
                
            # If maxresdefault fails, try hqdefault
            async with session.get(hq_thumbnail_url) as response:
                if response.status == 200:
                    data = await response.read()
                    # Save the thumbnail
                    with open(thumbnail_path, "wb") as f:
                        f.write(data)
                    return thumbnail_path
                
            # If both fail, return None
            return None
        except Exception as e:
            print(f"Error downloading thumbnail: {str(e)}")
            return None

# Function to format duration
def format_duration(duration_str):
    if isinstance(duration_str, str) and ":" in duration_str:
        return duration_str

    if isinstance(duration_str, str):
        try:
            duration_str = int(duration_str)
        except ValueError:
            return duration_str

    if isinstance(duration_str, int):
        minutes, seconds = divmod(duration_str, 60)
        return f"{minutes}:{seconds:02d}"

    return str(duration_str)

def create_music_caption(track_info, queue=None, current_seconds=None):
    """
    Create a caption for the music control message
    
    Args:
        track_info: Track information dictionary
        queue: Queue of tracks
        current_seconds: Current playback position in seconds
        
    Returns:
        str: Caption for the music control message
    """
    caption = f"🎵 **Now Playing**\n\n"
    caption += f"**Title:** {track_info.get('title', 'Unknown')}\n"
    
    if 'artist' in track_info and track_info['artist']:
        caption += f"**Artist:** {track_info.get('artist', 'Unknown')}\n"
        
    if 'album' in track_info and track_info['album']:
        caption += f"**Album:** {track_info.get('album', 'Unknown')}\n"
        
    if 'duration' in track_info and track_info['duration']:
        caption += f"**Duration:** {track_info.get('duration', 'Unknown')}\n"
    
    # Add current position if available
    if current_seconds is not None:
        current_position = format_duration(current_seconds)
        caption += f"**Current Position:** {current_position}\n"
    
    # Add queue info if available
    if queue and len(queue) > 0:
        caption += f"\n**Queue:** {len(queue)} tracks\n"
        # Show next 3 tracks in queue
        for i, track in enumerate(queue[:3]):
            caption += f"{i+1}. {track.get('title', 'Unknown')} - {track.get('artist', 'Unknown')}\n"
        if len(queue) > 3:
            caption += f"... and {len(queue) - 3} more\n"
    
    return caption 

def get_music_control_keyboard(is_playing=True, has_queue=False, is_repeating=False):
    # Create the keyboard
    keyboard = [
        [
            InlineKeyboardButton("⏸️ Pause" if is_playing else "▶️ Resume", callback_data="playpause"),
            InlineKeyboardButton("⏭️ Next", callback_data="next"),
            InlineKeyboardButton("🔂" if is_repeating else "1️⃣", callback_data="repeat")
        ],
        [
            InlineKeyboardButton("⏹️ Stop", callback_data="stop")
        ]
    ]
    return InlineKeyboardMarkup(keyboard)


