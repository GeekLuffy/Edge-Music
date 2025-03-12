from youtubesearchpython.__future__ import VideosSearch
import os
import re
import time
import asyncio
import hashlib
import logging
import tempfile
import subprocess
import yt_dlp
from typing import Dict, List, Optional, Union, Any
from dotenv import load_dotenv
from pyrogram import Client, filters
from pyrogram.types import Message, InlineKeyboardMarkup, InlineKeyboardButton
from pytgcalls import PyTgCalls
from pytgcalls.types import AudioPiped
from pytgcalls.types.input_stream.quality import HighQualityAudio
from pytgcalls.types import AudioParameters

# Import our helpers and callbacks
from spotify_bot.callbacks import register_callbacks
from spotify_bot.helpers import download_thumbnail, format_duration, create_music_caption, get_music_control_keyboard
try:
    # Try relative imports if the above fails
    from .callbacks import register_callbacks
    from .helpers import download_thumbnail, format_duration, create_music_caption, get_music_control_keyboard
except ImportError:
    pass

load_dotenv()

# Load environment variables
API_ID = os.getenv('API_ID')
API_HASH = os.getenv('API_HASH')
BOT_TOKEN = os.getenv('BOT_TOKEN')
USER_SESSION = os.getenv('USER_SESSION')
ASSISTANT_ID = int(os.getenv('ASSISTANT_ID'))

class MusicBot:
    def __init__(self):
        self.app = Client(
            "music_bot",
            api_id=API_ID,
            api_hash=API_HASH,
            bot_token=BOT_TOKEN
        )
        
        self.user = Client(
            "user_client",
            api_id=API_ID,
            api_hash=API_HASH,
            session_string=USER_SESSION
        )
        
        self.call_manager = PyTgCalls(self.user)
        
        self.queue = {}  # Changed to dict to store per-chat queues
        self.current_track = {}  # Changed to dict to store per-chat current tracks
        self.is_playing = {}  # Changed to dict to store per-chat playing status
        self.group_calls = {}  # Changed to dict to store per-chat group calls
        self.active_calls = {}  # New dict to track active calls
        self.control_messages = {}  # New dict to store control messages
        
        # Create download directory if it doesn't exist
        self.download_dir = "downloads"
        os.makedirs(self.download_dir, exist_ok=True)
        
        # Create thumbnails directory if it doesn't exist
        os.makedirs("thumbnails", exist_ok=True)
        
        # Define options for youtube-dl
        self.ydl_opts = {
            'format': 'bestaudio/best',
            'outtmpl': os.path.join(self.download_dir, '%(id)s'),  # No extension here
            'postprocessors': [{
                'key': 'FFmpegExtractAudio',
                'preferredcodec': 'mp3',
                'preferredquality': '320',
            }],
            'quiet': True,
            'no_warnings': True,
        }
        
        self.register_handlers()
        # Register callback handlers
        self.register_callbacks()

    def register_handlers(self):
        @self.app.on_message(filters.command("start"))
        async def start_command(client: Client, message: Message):
            await self.start_command(client, message)
            
        @self.app.on_message(filters.command("play"))
        async def play_command(client: Client, message: Message):
            await self.play_command(client, message)
            
        @self.app.on_message(filters.command("pause"))
        async def pause_command(client: Client, message: Message):
            await self.pause_command(client, message)
            
        @self.app.on_message(filters.command("resume"))
        async def resume_command(client: Client, message: Message):
            await self.resume_command(client, message)
            
        @self.app.on_message(filters.command("skip"))
        async def skip_command(client: Client, message: Message):
            await self.skip_command(client, message)
            
        @self.app.on_message(filters.command("stop"))
        async def stop_command(client: Client, message: Message):
            await self.stop_command(client, message)
            
        @self.app.on_message(filters.command("queue"))
        async def queue_command(client: Client, message: Message):
            await self.queue_command(client, message)
            
        @self.app.on_message(filters.command("refresh"))
        async def refresh_command(client: Client, message: Message):
            await self.refresh_command(client, message)
            
        @self.app.on_message(filters.command("seek"))
        async def seek_command(client: Client, message: Message):
            await self.seek_command(client, message)

    async def process_play_request(self, message: Message, query: str, wait_message: Message = None):
        """Process a play request from a user"""
        chat_id = message.chat.id

        # Initialize chat-specific structures if they don't exist
        if chat_id not in self.queue:
            self.queue[chat_id] = []
        if chat_id not in self.current_track:
            self.current_track[chat_id] = None
        if chat_id not in self.is_playing:
            self.is_playing[chat_id] = False

        # Check if the query is a YouTube URL
        youtube_regex = r'(?:https?:\/\/)?(?:www\.)?(?:youtube\.com\/watch\?v=|youtu\.be\/)([a-zA-Z0-9_-]+)'
        match = re.match(youtube_regex, query)
        
        if match:
            # Direct YouTube URL
            video_id = match.group(1)
            try:
                with yt_dlp.YoutubeDL({'quiet': True}) as ydl:
                    video_info = ydl.extract_info(f"https://www.youtube.com/watch?v={video_id}", download=False)
                
                # Format video information
                result = {
                    'title': video_info['title'],
                    'link': f"https://www.youtube.com/watch?v={video_id}",
                    'duration': format_duration(video_info.get('duration', 0)),
                    'thumbnails': video_info.get('thumbnails', [{'url': None}]),
                    'id': video_id
                }
            except Exception as e:
                if wait_message:
                    try:
                        await wait_message.delete()
                    except Exception as e:
                        print(f"Error deleting wait message: {str(e)}")
                await message.reply(f"Error processing YouTube URL: {str(e)}")
                return
        else:
            # Search for videos
            search = VideosSearch(query, limit=1)
            results = await search.next()
            
            if not results["result"]:
                if wait_message:
                    try:
                        await wait_message.delete()
                    except Exception as e:
                        print(f"Error deleting wait message: {str(e)}")
                await message.reply("No results found for your query.")
                return
                
            # Get the first result
            result = results["result"][0]

        # Extract video information
        video_info = {
            'title': result['title'],
            'url': result['link'] if match else result['link'],
            'duration': result['duration'] if not match else format_duration(int(video_info.get('duration', 0))),
            'thumbnail': result['thumbnails'][0]['url'] if not match else video_info['thumbnails'][0]['url'],
            'video_id': result['id'] if not match else video_id
        }
        
        # Download thumbnail
        thumbnail_path = await download_thumbnail(video_info['video_id'])
        
        # Create caption
        caption = create_music_caption(video_info)
        
        # If no track is currently playing, play this one
        if not self.current_track[chat_id]:
            self.current_track[chat_id] = video_info
            
            # Download the audio file
            try:
                # Update wait message
                if wait_message:
                    try:
                        await wait_message.edit_text(f"⬇️ Downloading audio for: {video_info['title']}")
                    except Exception as e:
                        print(f"Error updating wait message: {str(e)}")
                
                audio_file = await self.download_audio(video_info['url'])
                print(f"Downloaded audio file: {audio_file}")
            except Exception as e:
                print(f"Error downloading audio: {str(e)}")
                if wait_message:
                    try:
                        await wait_message.delete()
                    except Exception as e:
                        print(f"Error deleting wait message: {str(e)}")
                await message.reply(f"Error downloading audio: {str(e)}")
                return

            # Delete wait message if it exists
            if wait_message:
                try:
                    await wait_message.delete()
                except Exception as e:
                    print(f"Error deleting wait message: {str(e)}")
            
            # Create a control message
            await self.create_control_message(chat_id, message)
            
            # Start streaming
            await self.start_streaming(chat_id, audio_file, message)
            
            # Register callbacks if not already registered
            self.register_callbacks()
        else:
            # Add to queue
            position = len(self.queue[chat_id]) + 1  # Position in queue (1-indexed)
            self.queue[chat_id].append(video_info)
            
            # Create caption
            caption = create_music_caption(video_info)
            
            # Delete wait message if it exists
            if wait_message:
                try:
                    await wait_message.delete()
                except Exception as e:
                    print(f"Error deleting wait message: {str(e)}")
            
            # Send message with thumbnail
            if thumbnail_path:
                await message.reply_photo(
                    photo=thumbnail_path,
                    caption=f"{caption}\n\nAdded to queue at position {position}."
                )
            else:
                await message.reply_text(
                    f"{caption}\n\nAdded to queue at position {position}."
                )
                
            # Update the control message keyboard if it exists
            if chat_id in self.control_messages:
                try:
                    # Get the current keyboard and update it
                    has_queue = chat_id in self.queue and len(self.queue[chat_id]) > 0
                    is_playing = chat_id in self.is_playing and self.is_playing[chat_id]
                    keyboard = get_music_control_keyboard(is_playing=is_playing, has_queue=has_queue)
                    
                    # Update the caption with queue information
                    if chat_id in self.current_track and self.current_track[chat_id]:
                        updated_caption = create_music_caption(
                            self.current_track[chat_id], 
                            queue=self.queue[chat_id]
                        )
                        
                        # Edit the message to update both caption and keyboard
                        await self.control_messages[chat_id].edit_caption(
                            caption=updated_caption,
                            reply_markup=keyboard
                        )
                    else:
                        # Just update the keyboard if we can't update the caption
                        await self.control_messages[chat_id].edit_reply_markup(
                            reply_markup=keyboard
                        )
                except Exception as e:
                    print(f"Error updating control message: {str(e)}")

    async def download_audio(self, track_info) -> str:
        """Download audio from a YouTube video"""
        try:
            # Handle both URL strings and track_info dictionaries
            url = track_info['url'] if isinstance(track_info, dict) else track_info
            
            # Create a unique filename based on the URL
            filename = f"audio_{hashlib.md5(url.encode()).hexdigest()}.mp3"
            output_file = os.path.join(self.download_dir, filename)
            
            # Check if the file already exists
            if os.path.exists(output_file):
                print(f"Audio file already exists: {output_file}")
                return output_file
                
            # Check if file with double extension exists (fix for previous downloads)
            double_ext_file = f"{output_file}.mp3"
            if os.path.exists(double_ext_file):
                print(f"Found file with double extension: {double_ext_file}")
                # Rename the file to have the correct extension
                try:
                    os.rename(double_ext_file, output_file)
                    print(f"Renamed file to: {output_file}")
                    return output_file
                except Exception as e:
                    print(f"Error renaming file: {str(e)}")
                    # If we can't rename, use the file with double extension
                    return double_ext_file
            
            # Ensure download directory exists
            os.makedirs(self.download_dir, exist_ok=True)
            
            # Define options for youtube-dl
            ydl_opts = {
                'format': 'bestaudio/best',
                'outtmpl': output_file,  # No extension here, it will be added by the postprocessor
                'postprocessors': [{
                    'key': 'FFmpegExtractAudio',
                    'preferredcodec': 'mp3',
                    'preferredquality': '192',
                }],
                'quiet': True,
                'no_warnings': True,
            }
            
            # Download the audio
            with yt_dlp.YoutubeDL(ydl_opts) as ydl:
                print(f"Downloading audio from: {url}")
                ydl.download([url])
                
            # Check if the file was created
            if os.path.exists(output_file):
                print(f"Downloaded audio file: {output_file}")
                return output_file
            
            # Check if file with double extension was created
            if os.path.exists(double_ext_file):
                print(f"Downloaded audio file with double extension: {double_ext_file}")
                # Try to rename the file
                try:
                    os.rename(double_ext_file, output_file)
                    print(f"Renamed file to: {output_file}")
                    return output_file
                except Exception as e:
                    print(f"Error renaming file: {str(e)}")
                    # If we can't rename, use the file with double extension
                    return double_ext_file
                
            # If we get here, the file wasn't created
            raise Exception(f"File not created after download: {output_file}")
        except Exception as e:
            print(f"Error downloading audio: {str(e)}")
            raise

    async def start_streaming(self, chat_id, audio_file, message=None):
        """Start streaming audio in a voice chat"""
        try:
            print(f"Starting streaming in chat {chat_id}")
            
            # Check if we have a current track
            if chat_id not in self.current_track or not self.current_track[chat_id]:
                print(f"No current track for chat {chat_id}")
                return False
                
            # Check if the audio file exists
            if not os.path.exists(audio_file):
                print(f"Audio file does not exist: {audio_file}")
                # Check if file with double extension exists
                double_ext_file = f"{audio_file}.mp3"
                if os.path.exists(double_ext_file):
                    print(f"Found file with double extension: {double_ext_file}")
                    audio_file = double_ext_file
                else:
                    error_msg = f"Audio file not found: {audio_file}"
                    print(error_msg)
                    if message:
                        await message.reply(f"Error: {error_msg}")
                    return False
                
            # First try to get a fresh reference to the group call
            try:
                # Try to get the current group call
                current_call = await self.call_manager.get_call(chat_id)
                if current_call:
                    self.group_calls[chat_id] = current_call
                    print(f"Got fresh reference to group call for chat {chat_id}")
                    # Mark the call as active
                    self.active_calls[chat_id] = True
            except Exception as e:
                print(f"Error getting fresh reference to group call: {str(e)}")
            
            # Check if there's an active group call
            is_active = await self.is_group_call_active(chat_id)
            print(f"Group call is active: {is_active}")
            
            # Also check active_calls directly
            active_call = self.active_calls.get(chat_id, False)
            print(f"Active call from dictionary: {active_call}")
            
            if is_active or active_call:
                print(f"Group call is already active, trying to change stream")
                # Send a message that we're changing the stream
                if message:
                    status_msg = await message.reply("🔄 Changing stream...")
                
                try:
                    # Create an AudioPiped object with AudioParameters
                    audio_stream = AudioPiped(
                        audio_file,
                        AudioParameters(
                            bitrate=48000,
                        ),
                    )
                    
                    # Try to change the stream using the call manager
                    await self.call_manager.change_stream(
                        chat_id,
                        audio_stream
                    )
                    print(f"Successfully changed stream with call_manager for chat {chat_id}")
                    # Mark the call as active
                    self.active_calls[chat_id] = True
                    self.is_playing[chat_id] = True
                    
                    # Delete the status message
                    if message and 'status_msg' in locals():
                        try:
                            await status_msg.delete()
                        except Exception as e:
                            print(f"Error deleting status message: {str(e)}")
                            
                    # Create a control message if message is provided
                    if message and chat_id in self.current_track and self.current_track[chat_id]:
                        # Create a new control message
                        await self.create_control_message(chat_id, message)
                        
                        # Start periodic updates
                        await self.start_periodic_updates(chat_id)
                    
                    return True
                except Exception as e:
                    print(f"Error changing stream with call_manager: {str(e)}")
                    # If we get "Already joined into group call" error, mark the call as active anyway
                    if "Already joined into group call" in str(e):
                        self.active_calls[chat_id] = True
                        self.is_playing[chat_id] = True
                        print(f"Already in group call for chat {chat_id}, marking as active")
                        
                        # Delete the status message
                        if message and 'status_msg' in locals():
                            try:
                                await status_msg.delete()
                            except Exception as e:
                                print(f"Error deleting status message: {str(e)}")
                                
                        return True
                    # Otherwise, try to leave and rejoin
                    await self.stop_streaming(chat_id, message)
                    # Wait a moment before rejoining
                    await asyncio.sleep(1)
                    
                    # Delete the status message
                    if message and 'status_msg' in locals():
                        try:
                            await status_msg.delete()
                        except Exception as e:
                            print(f"Error deleting status message: {str(e)}")
            
            # Try to join a new group call
            try:
                # Send a message that we're joining a voice chat
                if message:
                    status_msg = await message.reply("🎵 Joining voice chat...")
                    
                print(f"Joining new group call in chat {chat_id}")
                
                # Create an AudioPiped object with AudioParameters
                audio_stream = AudioPiped(
                    audio_file,
                    AudioParameters(
                        bitrate=48000,
                    ),
                )
                
                self.group_calls[chat_id] = await self.call_manager.join_group_call(
                    chat_id,
                    audio_stream
                )
                print(f"Successfully joined group call in chat {chat_id}")
                # Mark the call as active
                self.active_calls[chat_id] = True
                self.is_playing[chat_id] = True
                
                # Delete the status message
                if message and 'status_msg' in locals():
                    try:
                        await status_msg.delete()
                    except Exception as e:
                        print(f"Error deleting status message: {str(e)}")
                
                # Create a control message if message is provided
                if message and chat_id in self.current_track and self.current_track[chat_id]:
                    # Create a new control message
                    await self.create_control_message(chat_id, message)
                    
                    # Start periodic updates
                    await self.start_periodic_updates(chat_id)
                
                return True
            except Exception as e:
                print(f"Error joining group call: {str(e)}")
                # If we get "Already joined into group call" error, mark the call as active anyway
                if "Already joined into group call" in str(e):
                    self.active_calls[chat_id] = True
                    self.is_playing[chat_id] = True
                    print(f"Already in group call for chat {chat_id}, marking as active")
                    
                    # Delete the status message
                    if message and 'status_msg' in locals():
                        try:
                            await status_msg.delete()
                        except Exception as e:
                            print(f"Error deleting status message: {str(e)}")
                    
                    # Try to change the stream using the call manager directly
                    try:
                        # Create an AudioPiped object with AudioParameters
                        audio_stream = AudioPiped(
                            audio_file,
                            AudioParameters(
                                bitrate=48000,
                            ),
                        )
                        
                        await self.call_manager.change_stream(
                            chat_id,
                            audio_stream
                        )
                        print(f"Successfully changed stream using call_manager.change_stream after 'Already joined' error")
                        
                        # Create a control message if message is provided
                        if message and chat_id in self.current_track and self.current_track[chat_id]:
                            # Create a new control message
                            await self.create_control_message(chat_id, message)
                        
                        return True
                    except Exception as e2:
                        print(f"Error changing stream with call_manager after 'Already joined' error: {str(e2)}")
                        if message:
                            await message.reply(f"Error changing stream: {str(e2)}")
                        return False
                else:
                    # Delete the status message
                    if message and 'status_msg' in locals():
                        try:
                            await status_msg.delete()
                        except Exception as e:
                            print(f"Error deleting status message: {str(e)}")
                            
                    if message:
                        await message.reply(f"Error joining voice chat: {str(e)}")
                    return False
        except Exception as e:
            print(f"Error in start_streaming: {str(e)}")
            if message:
                await message.reply(f"Error starting stream: {str(e)}")
            return False

    async def cleanup_audio_file(self, audio_file: str):
        """Delete an audio file, its thumbnail, and any related seeked files if they exist"""
        try:
            if not audio_file:
                return

            print(f"Starting cleanup for audio file: {audio_file}")
            
            # Get the directory and filename
            directory = os.path.dirname(audio_file)
            filename = os.path.basename(audio_file)
            
            # Extract hash from filename
            file_hash = None
            
            # Check if it's a seeked file
            if filename.startswith('seeked_'):
                # Extract hash from seeked filename (format: seeked_<hash>_<position>.mp3)
                parts = filename.split('_')
                if len(parts) > 1:
                    file_hash = parts[1]
            # Check if it's an original file
            elif filename.startswith('audio_'):
                # Extract hash from original filename (format: audio_<hash>.mp3)
                file_hash = filename[6:-4]  # Remove 'audio_' prefix and '.mp3' extension
            
            if file_hash:
                print(f"Cleaning up files with hash: {file_hash}")
                
                # List all files in the download directory
                for file in os.listdir(self.download_dir):
                    # Check if file is related (starts with audio_<hash> or seeked_<hash>)
                    if file.startswith(f'audio_{file_hash}') or file.startswith(f'seeked_{file_hash}'):
                        file_path = os.path.join(self.download_dir, file)
                        try:
                            if os.path.exists(file_path):
                                os.remove(file_path)
                                print(f"Successfully deleted: {file_path}")
                        except Exception as e:
                            print(f"Error deleting file {file_path}: {str(e)}")
            
                # Clean up thumbnail
                thumbnail_path = os.path.join('thumbnails', f"{file_hash}.jpg")
                if os.path.exists(thumbnail_path):
                    try:
                        os.remove(thumbnail_path)
                        print(f"Successfully deleted thumbnail: {thumbnail_path}")
                    except Exception as e:
                        print(f"Error deleting thumbnail {thumbnail_path}: {str(e)}")
            else:
                print(f"Could not extract hash from filename: {filename}")
                # Try to delete the specific file if it exists
                if os.path.exists(audio_file):
                    try:
                        os.remove(audio_file)
                        print(f"Deleted specific file: {audio_file}")
                    except Exception as e:
                        print(f"Error deleting specific file: {str(e)}")

        except Exception as e:
            print(f"Error in cleanup_audio_file: {str(e)}")

    async def stop_streaming(self, chat_id, message=None):
        """Stop streaming and clean up resources"""
        try:
            print(f"Attempting to stop streaming in chat {chat_id}")
            
            # Get the current track info
            current_track = self.current_track.get(chat_id)
            if current_track:
                # Clean up using the audio file
                audio_file = current_track.get('audio_file')
                if audio_file:
                    await self.cleanup_audio_file(audio_file)
            
            # Original stop_streaming logic
            if chat_id in self.group_calls and self.group_calls[chat_id]:
                try:
                    await self.call_manager.leave_group_call(chat_id)
                    self.group_calls[chat_id] = None
                except Exception as e:
                    print(f"Error leaving group call: {str(e)}")
            
            # Clear all track-related data
            self.current_track[chat_id] = None
            if chat_id in self.queue:
                self.queue[chat_id].clear()
            if chat_id in self.is_playing:
                self.is_playing[chat_id] = False
            if hasattr(self, 'playback_start_times') and chat_id in self.playback_start_times:
                del self.playback_start_times[chat_id]

            print(f"Successfully cleaned up resources for chat {chat_id}")

        except Exception as e:
            print(f"Error in stop_streaming: {str(e)}")

    async def handle_track_finish(self, message: Message):
        """Handle when a track finishes playing"""
        chat_id = message.chat.id
        
        print(f"Track finished in chat {chat_id}")
        
        # Check if there are more tracks in the queue
        if chat_id in self.queue and self.queue[chat_id]:
            print(f"Playing next track from queue in chat {chat_id}")
            await self.skip_track(message)
        else:
            print(f"No more tracks in queue for chat {chat_id}")
            self.current_track[chat_id] = None
            self.is_playing[chat_id] = False
            await self.stop_streaming(chat_id, message)
            
            # Delete the control message if it exists
            if chat_id in self.control_messages:
                try:
                    await self.control_messages[chat_id].delete()
                    del self.control_messages[chat_id]
                except Exception as e:
                    print(f"Error deleting control message: {str(e)}")
            
            await message.reply("Queue finished. Left the voice chat.")

    async def start(self):
        print("Bot is starting...")
        # Clean up any files with double extensions
        self.cleanup_double_extensions()
        await self.app.start()
        await self.user.start()
        await self.call_manager.start()
        
        # Set up stream end handler
        @self.call_manager.on_stream_end()
        async def stream_end_handler(_, update):
            chat_id = update.chat_id
            print(f"Stream ended in chat {chat_id}")
            
            # Get the current audio file path before moving to next track
            current_audio = None
            if chat_id in self.current_track and self.current_track[chat_id]:
                try:
                    url = self.current_track[chat_id]['url']
                    filename = f"audio_{hashlib.md5(url.encode()).hexdigest()}.mp3"
                    current_audio = os.path.join(self.download_dir, filename)
                except Exception as e:
                    print(f"Error getting current audio file path: {str(e)}")

            # Check if there are more tracks in the queue
            if chat_id in self.queue and self.queue[chat_id]:
                print(f"Playing next track from queue in chat {chat_id}")
                
                # Delete the current audio file before playing next track
                if current_audio:
                    await self.cleanup_audio_file(current_audio)
                
                # Get the next track from the queue
                next_track = self.queue[chat_id].pop(0)
                self.current_track[chat_id] = next_track
                
                try:
                    # Download the audio file
                    audio_file = await self.download_audio(next_track['url'])
                    print(f"Downloaded audio file: {audio_file}")
                    
                    # Create audio stream
                    audio_stream = AudioPiped(
                        audio_file,
                        AudioParameters(
                            bitrate=48000,
                        ),
                    )
                    
                    # Try to change the stream
                    await self.call_manager.change_stream(
                        chat_id,
                        audio_stream
                    )
                    print(f"Successfully changed stream to next track in chat {chat_id}")
                    
                    # Update playback status
                    self.is_playing[chat_id] = True
                    if not hasattr(self, 'playback_start_times'):
                        self.playback_start_times = {}
                    self.playback_start_times[chat_id] = time.time()
                    
                    # Update the control message
                    await self.update_control_message(chat_id)
                except Exception as e:
                    print(f"Error playing next track: {str(e)}")
                    await self.app.send_message(
                        chat_id,
                        f"Error playing next track: {str(e)}"
                    )
            else:
                print(f"No more tracks in queue for chat {chat_id}")
                # Delete the current audio file since playback is finished
                if current_audio:
                    await self.cleanup_audio_file(current_audio)
                
                # Clean up resources
                self.current_track[chat_id] = None
                self.is_playing[chat_id] = False
                await self.stop_streaming(chat_id, None)
                
                # Delete the control message if it exists
                if chat_id in self.control_messages:
                    try:
                        await self.control_messages[chat_id].delete()
                        del self.control_messages[chat_id]
                    except Exception as e:
                        print(f"Error deleting control message: {str(e)}")
                
                # Send message about queue completion
                await self.app.send_message(chat_id, "Queue finished. Left the voice chat.")
        
        print("Bot is running...")
        await asyncio.sleep(999999)  # Keep the bot running

    def cleanup_double_extensions(self):
        """Clean up any files with double extensions in the downloads directory"""
        try:
            print("Cleaning up files with double extensions...")
            if not os.path.exists(self.download_dir):
                os.makedirs(self.download_dir, exist_ok=True)
                return
                
            # Get all files in the downloads directory
            files = os.listdir(self.download_dir)
            for file in files:
                # Check if the file has a double extension
                if file.endswith('.mp3.mp3'):
                    old_path = os.path.join(self.download_dir, file)
                    new_path = os.path.join(self.download_dir, file[:-4])  # Remove the last .mp3
                    try:
                        print(f"Renaming {old_path} to {new_path}")
                        os.rename(old_path, new_path)
                    except Exception as e:
                        print(f"Error renaming file: {str(e)}")
            
            print("Cleanup completed.")
        except Exception as e:
            print(f"Error during cleanup: {str(e)}")

    def run(self):
        asyncio.get_event_loop().run_until_complete(self.start())

    async def is_group_call_active(self, chat_id):
        """Check if a group call is active for the given chat_id"""
        print(f"Checking if group call is active for chat {chat_id}")
        print(f"Group calls: {self.group_calls}")
        print(f"Active calls: {self.active_calls}")
        
        # First check if the chat_id exists in the active_calls dictionary
        if chat_id in self.active_calls and self.active_calls[chat_id]:
            print(f"Chat {chat_id} has an active call according to active_calls")
            return True
            
        # If not in active_calls, check the group_calls dictionary
        if chat_id not in self.group_calls:
            print(f"Chat {chat_id} not in group_calls dictionary")
            return False
            
        # Then check if the group call object is not None
        if self.group_calls[chat_id] is None:
            print(f"Group call for chat {chat_id} is None")
            return False
            
        # Check if the group call has an is_connected attribute and it's True
        try:
            is_connected = hasattr(self.group_calls[chat_id], 'is_connected') and self.group_calls[chat_id].is_connected
            print(f"Group call for chat {chat_id} is_connected: {is_connected}")
            # Update active_calls based on the result
            self.active_calls[chat_id] = is_connected
            return is_connected
        except Exception as e:
            print(f"Error checking if group call is connected: {str(e)}")
            # If we can't check, assume it's active if it exists
            self.active_calls[chat_id] = True
            return True

    # Methods for handling callbacks
    async def pause_stream(self, chat_id):
        """Pause the stream for a specific chat"""
        try:
            print(f"Pausing stream in chat {chat_id}")
            
            # If we have a group call object, try to pause it
            if chat_id in self.group_calls and self.group_calls[chat_id]:
                # First try to get a fresh reference to the group call
                try:
                    # Try to get the current group call
                    current_call = await self.call_manager.get_call(chat_id)
                    if current_call:
                        self.group_calls[chat_id] = current_call
                        print(f"Got fresh reference to group call for chat {chat_id}")
                except Exception as e:
                    print(f"Error getting fresh reference to group call: {str(e)}")
                
                # Now try to pause the stream
                try:
                    await self.group_calls[chat_id].pause_stream()
                    print(f"Successfully called pause_stream for chat {chat_id}")
                except Exception as e:
                    print(f"Error calling pause_stream: {str(e)}")
                    # Try alternative method
                    try:
                        await self.call_manager.pause_stream(chat_id)
                        print(f"Successfully called call_manager.pause_stream for chat {chat_id}")
                    except Exception as e2:
                        print(f"Error calling call_manager.pause_stream: {str(e2)}")
                        raise e2
            else:
                # Try to pause using the call manager directly
                await self.call_manager.pause_stream(chat_id)
                print(f"Successfully called call_manager.pause_stream for chat {chat_id}")
            
            # Update status
            self.is_playing[chat_id] = False
            
            # Store the elapsed time when paused
            if hasattr(self, 'playback_start_times') and chat_id in self.playback_start_times:
                if not hasattr(self, 'paused_positions'):
                    self.paused_positions = {}
                self.paused_positions[chat_id] = int(time.time() - self.playback_start_times[chat_id])
                print(f"Stored paused position for chat {chat_id}: {self.paused_positions[chat_id]} seconds")
            
            print(f"Successfully paused stream in chat {chat_id}")
            return True
        except Exception as e:
            print(f"Error pausing stream: {str(e)}")
            # Still mark as paused if there was an error
            self.is_playing[chat_id] = False
            return False
            
    async def resume_stream(self, chat_id):
        """Resume the stream for a specific chat"""
        try:
            print(f"Resuming stream in chat {chat_id}")
            
            # If we have a group call object, try to resume it
            if chat_id in self.group_calls and self.group_calls[chat_id]:
                # First try to get a fresh reference to the group call
                try:
                    # Try to get the current group call
                    current_call = await self.call_manager.get_call(chat_id)
                    if current_call:
                        self.group_calls[chat_id] = current_call
                        print(f"Got fresh reference to group call for chat {chat_id}")
                except Exception as e:
                    print(f"Error getting fresh reference to group call: {str(e)}")
                
                # Now try to resume the stream
                try:
                    await self.group_calls[chat_id].resume_stream()
                    print(f"Successfully called resume_stream for chat {chat_id}")
                except Exception as e:
                    print(f"Error calling resume_stream: {str(e)}")
                    # Try alternative method
                    try:
                        await self.call_manager.resume_stream(chat_id)
                        print(f"Successfully called call_manager.resume_stream for chat {chat_id}")
                    except Exception as e2:
                        print(f"Error calling call_manager.resume_stream: {str(e2)}")
                        raise e2
            else:
                # Try to resume using the call manager directly
                await self.call_manager.resume_stream(chat_id)
                print(f"Successfully called call_manager.resume_stream for chat {chat_id}")
            
            # Update status
            self.is_playing[chat_id] = True
            
            # Adjust the start time to account for the paused duration
            if hasattr(self, 'paused_positions') and chat_id in self.paused_positions:
                if not hasattr(self, 'playback_start_times'):
                    self.playback_start_times = {}
                # Set the start time to now minus the elapsed time when paused
                self.playback_start_times[chat_id] = time.time() - self.paused_positions[chat_id]
                print(f"Adjusted start time for chat {chat_id} to account for {self.paused_positions[chat_id]} seconds of playback")
                # Start periodic updates again
                await self.start_periodic_updates(chat_id)
            
            print(f"Successfully resumed stream in chat {chat_id}")
            return True
        except Exception as e:
            print(f"Error resuming stream: {str(e)}")
            # Still mark as resumed if there was an error
            self.is_playing[chat_id] = True
            return False
            
    async def skip_track_callback(self, message: Message):
        """Skip to the next track (callback version)"""
        # This method is now deprecated as the skip_track method handles everything
        # Just call the regular skip_track method
        await self.skip_track(message)

    def register_callbacks(self):
        """Register callback handlers for inline buttons"""
        try:
            # Try to use the already imported register_callbacks function
            from spotify_bot.callbacks import register_callbacks
            register_callbacks(self)
        except Exception as e:
            print(f"Error registering callbacks: {str(e)}")
            # If that fails, try to import it again
            try:
                from spotify_bot.callbacks import register_callbacks as reg_cb
                reg_cb(self)
            except ImportError:
                from .callbacks import register_callbacks as reg_cb
                reg_cb(self)

    async def update_control_message(self, chat_id, force_update=False):
        """Update the control message with current track info and controls"""
        if chat_id not in self.current_track or not self.current_track[chat_id]:
            return
        
        # Check if we need to update
        current_time = time.time()
        if not force_update and hasattr(self, 'last_update_times') and chat_id in self.last_update_times:
            # Only update every 5 seconds unless forced
            if current_time - self.last_update_times[chat_id] < 5:
                return
        
        # Update the last update time
        if not hasattr(self, 'last_update_times'):
            self.last_update_times = {}
        self.last_update_times[chat_id] = current_time
        
        # Get the current track info
        track_info = self.current_track[chat_id]
        
        # Create the caption
        caption = f"🎵 **Now Playing**\n\n"
        caption += f"**Title:** {track_info.get('title', 'Unknown')}\n"
        if 'artist' in track_info and track_info['artist']:
            caption += f"**Artist:** {track_info.get('artist', 'Unknown')}\n"
        if 'album' in track_info and track_info['album']:
            caption += f"**Album:** {track_info.get('album', 'Unknown')}\n"
        if 'duration' in track_info and track_info['duration']:
            caption += f"**Duration:** {track_info.get('duration', 'Unknown')}\n"
        
        # Calculate current position
        current_position = 0
        if hasattr(self, 'playback_start_times') and chat_id in self.playback_start_times:
            current_position = int(current_time - self.playback_start_times[chat_id])
        
        # Format the current position
        current_position_str = format_duration(current_position)
        caption += f"**Current Position:** {current_position_str}\n"
        
        # Add queue info
        if chat_id in self.queue and self.queue[chat_id]:
            caption += f"\n**Queue:** {len(self.queue[chat_id])} tracks\n"
            # Show next 3 tracks in queue
            for i, track in enumerate(self.queue[chat_id][:3]):
                caption += f"{i+1}. {track.get('title', 'Unknown')} - {track.get('artist', 'Unknown')}\n"
            if len(self.queue[chat_id]) > 3:
                caption += f"... and {len(self.queue[chat_id]) - 3} more\n"
        
        # Create the keyboard with controls using the helper function
        has_queue = chat_id in self.queue and len(self.queue[chat_id]) > 0
        is_playing = self.is_playing.get(chat_id, False)
        reply_markup = get_music_control_keyboard(is_playing=is_playing, has_queue=has_queue)
        
        # Check if we have a control message
        if chat_id in self.control_messages and self.control_messages[chat_id]:
            try:
                # Update the existing message
                current_caption = None
                try:
                    current_caption = self.control_messages[chat_id].caption
                except:
                    pass
                
                # Only update if the caption has changed or force update is True
                if force_update or current_caption != caption:
                    await self.control_messages[chat_id].edit_caption(
                        caption=caption,
                        reply_markup=reply_markup
                    )
            except Exception as e:
                print(f"Error updating control message: {str(e)}")
                # If we can't update, try to send a new one
                try:
                    # Get the thumbnail URL
                    thumbnail_url = track_info.get('thumbnail', None)
                    
                    # Send a new message with the thumbnail
                    if thumbnail_url:
                        self.control_messages[chat_id] = await self.app.send_photo(
                            chat_id=chat_id,
                            photo=thumbnail_url,
                            caption=caption,
                            reply_markup=reply_markup
                        )
                    else:
                        # If no thumbnail, send a text message
                        self.control_messages[chat_id] = await self.app.send_message(
                            chat_id=chat_id,
                            text=caption,
                            reply_markup=reply_markup
                        )
                except Exception as e2:
                    print(f"Error sending new control message: {str(e2)}")
        else:
            try:
                # Send a new control message
                # Get the thumbnail URL
                thumbnail_url = track_info.get('thumbnail', None)
                
                # Send a new message with the thumbnail
                if thumbnail_url:
                    self.control_messages[chat_id] = await self.app.send_photo(
                        chat_id=chat_id,
                        photo=thumbnail_url,
                        caption=caption,
                        reply_markup=reply_markup
                    )
                else:
                    # If no thumbnail, send a text message
                    self.control_messages[chat_id] = await self.app.send_message(
                        chat_id=chat_id,
                        text=caption,
                        reply_markup=reply_markup
                    )
            except Exception as e:
                print(f"Error sending control message: {str(e)}")

    async def create_control_message(self, chat_id, message):
        """
        Create a new control message
        
        Args:
            chat_id: Chat ID
            message: Message to reply to
        
        Returns:
            bool: True if successful, False otherwise
        """
        try:
            # Check if we have a current track
            if chat_id not in self.current_track or not self.current_track[chat_id]:
                return False
                
            # Delete the old control message if it exists
            if chat_id in self.control_messages:
                try:
                    await self.control_messages[chat_id].delete()
                except Exception as e:
                    print(f"Error deleting old control message: {str(e)}")
            
            # Download thumbnail
            thumbnail_path = await download_thumbnail(self.current_track[chat_id]['video_id'])
            
            # Get current playback position
            current_seconds = None
            if hasattr(self, 'playback_start_times') and chat_id in self.playback_start_times:
                current_seconds = int(time.time() - self.playback_start_times[chat_id])
            
            # Create caption
            caption = create_music_caption(
                self.current_track[chat_id], 
                queue=self.queue.get(chat_id, []),
                current_seconds=current_seconds
            )
            
            # Create keyboard
            has_queue = chat_id in self.queue and len(self.queue[chat_id]) > 0
            is_playing = chat_id in self.is_playing and self.is_playing[chat_id]
            keyboard = get_music_control_keyboard(
                is_playing=is_playing, 
                has_queue=has_queue
            )
            
            # Send message with thumbnail and controls
            if thumbnail_path:
                control_message = await message.reply_photo(
                    photo=thumbnail_path,
                    caption=caption,
                    reply_markup=keyboard
                )
            else:
                control_message = await message.reply_text(
                    caption,
                    reply_markup=keyboard
                )
            
            # Store the control message for later updates
            self.control_messages[chat_id] = control_message
            
            print(f"Created new control message for chat {chat_id}")
            return True
        except Exception as e:
            print(f"Error creating control message: {str(e)}")
            return False

    async def start_periodic_updates(self, chat_id):
        """
        Start periodic updates of the control message
        
        Args:
            chat_id: Chat ID
        """
        # Store the start time
        if not hasattr(self, 'playback_start_times'):
            self.playback_start_times = {}
        self.playback_start_times[chat_id] = time.time()
        
        # Initialize last update time
        if not hasattr(self, 'last_update_times'):
            self.last_update_times = {}
        self.last_update_times[chat_id] = 0
        
        # Start the update loop
        asyncio.create_task(self._update_loop(chat_id))
        
    async def _update_loop(self, chat_id):
        """
        Update loop for the control message
        
        Args:
            chat_id: Chat ID
        """
        try:
            # Update every 30 seconds instead of 10
            update_interval = 10
            
            while (chat_id in self.is_playing and self.is_playing[chat_id] and 
                   chat_id in self.active_calls and self.active_calls[chat_id] and
                   chat_id in self.current_track and self.current_track[chat_id]):
                
                # Calculate current position
                if chat_id in self.playback_start_times:
                    current_time = time.time()
                    elapsed = int(current_time - self.playback_start_times[chat_id])
                    
                    # Only update if enough time has passed since the last update
                    if current_time - self.last_update_times.get(chat_id, 0) >= update_interval:
                        # Update the control message
                        await self.update_control_message(chat_id, False)
                        # Update the last update time
                        self.last_update_times[chat_id] = current_time
                
                # Wait for a shorter interval to check conditions more frequently
                await asyncio.sleep(5)
                
            print(f"Update loop for chat {chat_id} stopped")
        except Exception as e:
            print(f"Error in update loop: {str(e)}")

    async def play_command(self, client: Client, message: Message):
        """Play music in a voice chat"""
        # Check if the message has a query
        if len(message.command) < 2:
            await message.reply("Please provide a song name or YouTube link.")
            return
            
        # Get the query from the message
        query = " ".join(message.command[1:])
        
        # Send a wait message
        wait_message = await message.reply("🔍 Searching and processing your request... Please wait.")
        
        # Process the play request
        await self.process_play_request(message, query, wait_message)
        
    async def pause_command(self, client: Client, message: Message):
        """Pause the currently playing music"""
        chat_id = message.chat.id
        
        print(f"Pause command received for chat {chat_id}")
        
        # Check if there is an active group call
        if not await self.is_group_call_active(chat_id):
            await message.reply("There is no active voice chat to pause.")
            return
            
        # Check if music is playing
        if chat_id not in self.is_playing or not self.is_playing[chat_id]:
            await message.reply("No music is currently playing.")
            return
            
        # Try to pause the stream
        success = await self.pause_stream(chat_id)
        
        if success:
            await message.reply("Music paused.")
            
            # Update the control message if it exists
            await self.update_control_message(chat_id)
        else:
            await message.reply("Failed to pause the music. Please try again.")
            
    async def resume_command(self, client: Client, message: Message):
        """Resume the paused music"""
        chat_id = message.chat.id
        
        print(f"Resume command received for chat {chat_id}")
        
        # Check if there is an active group call
        if not await self.is_group_call_active(chat_id):
            await message.reply("There is no active voice chat to resume.")
            return
            
        # Check if music is paused
        if chat_id in self.is_playing and self.is_playing[chat_id]:
            await message.reply("Music is already playing.")
            return
            
        # Try to resume the stream
        success = await self.resume_stream(chat_id)
        
        if success:
            await message.reply("Music resumed.")
            
            # Update the control message if it exists
            await self.update_control_message(chat_id)
        else:
            await message.reply("Failed to resume the music. Please try again.")
            
    async def skip_command(self, client: Client, message: Message):
        """Skip to the next track in the queue"""
        chat_id = message.chat.id
        
        print(f"Skip command received for chat {chat_id}")
        
        # Check if there is an active group call
        if not await self.is_group_call_active(chat_id):
            await message.reply("There is no active voice chat.")
            return
            
        # Check if there are songs in the queue
        if chat_id not in self.queue or not self.queue[chat_id]:
            await message.reply("No songs in the queue to skip to.")
            return
            
        # Call the skip_track method
        await self.skip_track(message)
        
    async def stop_command(self, client: Client, message: Message):
        """Stop the music and leave the voice chat"""
        chat_id = message.chat.id
        
        print(f"Stop command received for chat {chat_id}")
        
        # Check if there is an active group call
        if not await self.is_group_call_active(chat_id):
            await message.reply("There is no active voice chat to stop.")
            return
            
        # Try to stop streaming
        await self.stop_streaming(chat_id, message)
        
        # Delete the control message if it exists
        if chat_id in self.control_messages:
            try:
                await self.control_messages[chat_id].delete()
                del self.control_messages[chat_id]
            except Exception as e:
                print(f"Error deleting control message: {str(e)}")
        
        await message.reply("Music stopped and left the voice chat.")
        
    async def queue_command(self, client: Client, message: Message):
        """Show the current queue of tracks"""
        chat_id = message.chat.id
        
        print(f"Queue command received for chat {chat_id}")
        
        # Check if there is a current track
        if chat_id not in self.current_track or not self.current_track[chat_id]:
            await message.reply("No music is currently playing.")
            return
            
        # Create the queue message
        queue_text = "🎵 **Current Queue:**\n\n"
        
        # Add the current track
        queue_text += f"**Now Playing:**\n{create_music_caption(self.current_track[chat_id])}\n\n"
        
        # Add the queued tracks
        if chat_id in self.queue and self.queue[chat_id]:
            queue_text += "**Up Next:**\n"
            for i, track in enumerate(self.queue[chat_id], 1):
                queue_text += f"{i}. {track['title']} ({track['duration']})\n"
        else:
            queue_text += "**No tracks in queue.**"
            
        # Send the queue message
        await message.reply(queue_text)

    async def start_command(self, client: Client, message: Message):
        """Welcome message when the bot is started"""
        await message.reply(
            "👋 Welcome to the Music Bot!\n\n"
            "Use these commands to control the bot:\n"
            "/play <song name> - Play a song or add it to the queue\n"
            "/pause - Pause the current song\n"
            "/resume - Resume the paused song\n"
            "/skip - Skip to the next song in the queue\n"
            "/stop - Stop playing and leave the voice chat\n"
            "/queue - Show the current queue\n"
            "/refresh - Recreate the control message with current playback status\n"
            "/seek <seconds> - Skip forward by the specified number of seconds from current position\n\n"
            "You can also use the buttons below the music thumbnail to control playback."
        )

    async def skip_track(self, message: Message):
        """Skip to the next track in the queue"""
        chat_id = message.chat.id
        
        print(f"Skipping track in chat {chat_id}")
        
        # Send a wait message
        wait_message = await message.reply("⏭️ Skipping to next track... Please wait.")
        
        # Check if there's an active group call
        is_active = await self.is_group_call_active(chat_id)
        print(f"Group call is active: {is_active}")
        
        # Also check active_calls directly
        active_call = self.active_calls.get(chat_id, False)
        print(f"Active call from dictionary: {active_call}")
        
        # Check if there are songs in the queue
        has_queue = chat_id in self.queue and len(self.queue[chat_id]) > 0
        print(f"Has queue: {has_queue}")
        
        if not has_queue:
            # Delete wait message
            try:
                await wait_message.delete()
            except Exception as e:
                print(f"Error deleting wait message: {str(e)}")
                
            # If we have a current track, we can still skip it by stopping playback
            if self.current_track.get(chat_id) and (is_active or active_call):
                await self.stop_streaming(chat_id, message)
                await message.reply("Skipped the current track and stopped playback.")
                return
            else:
                await message.reply("No songs in the queue to skip to.")
                return
        
        # Get the next track from the queue
        next_track = self.queue[chat_id].pop(0)
        print(f"Next track: {next_track}")
        
        # Update the current track
        self.current_track[chat_id] = next_track
        
        # Update wait message
        try:
            await wait_message.edit_text(f"⬇️ Downloading audio for: {next_track['title']}")
        except Exception as e:
            print(f"Error updating wait message: {str(e)}")
        
        # Download the audio file
        try:
            audio_file = await self.download_audio(next_track['url'])
            print(f"Downloaded audio file: {audio_file}")
            
            # Check if the audio file exists
            if not os.path.exists(audio_file):
                print(f"Audio file does not exist: {audio_file}")
                # Check if file with double extension exists
                double_ext_file = f"{audio_file}.mp3"
                if os.path.exists(double_ext_file):
                    print(f"Found file with double extension: {double_ext_file}")
                    audio_file = double_ext_file
                else:
                    error_msg = f"Audio file not found: {audio_file}"
                    print(error_msg)
                    
                    # Delete wait message
                    try:
                        await wait_message.delete()
                    except Exception as e:
                        print(f"Error deleting wait message: {str(e)}")
                        
                    await message.reply(f"Error: {error_msg}")
                    # Try to play the next track in the queue if there is one
                    if self.queue[chat_id]:
                        await message.reply("Trying to play the next track in the queue...")
                        await self.skip_track(message)
                    return
        except Exception as e:
            print(f"Error downloading audio: {str(e)}")
            
            # Delete wait message
            try:
                await wait_message.delete()
            except Exception as e:
                print(f"Error deleting wait message: {str(e)}")
                
            await message.reply(f"Error downloading audio: {str(e)}")
            # Try to play the next track in the queue if there is one
            if self.queue[chat_id]:
                await message.reply("Trying to play the next track in the queue...")
                await self.skip_track(message)
            return
        
        # Update wait message
        try:
            await wait_message.edit_text(f"🔄 Changing stream to: {next_track['title']}")
        except Exception as e:
            print(f"Error updating wait message: {str(e)}")
        
        # If we have an active group call, try to change the stream
        if is_active or active_call:
            print(f"Changing stream in chat {chat_id}")
            try:
                # Create an AudioPiped object with AudioParameters
                audio_stream = AudioPiped(
                    audio_file,
                    AudioParameters(
                        bitrate=48000,
                    ),
                )
                
                # Try to change the stream using the call manager
                try:
                    await self.call_manager.change_stream(
                        chat_id,
                        audio_stream
                    )
                    print(f"Successfully changed stream with call_manager for chat {chat_id}")
                except Exception as e:
                    print(f"Error changing stream with call_manager: {str(e)}")
                    
                    # If changing stream fails, try to leave and rejoin
                    print("Trying to leave and rejoin the group call")
                    
                    # First try to leave
                    try:
                        await self.call_manager.leave_group_call(chat_id)
                        print(f"Successfully left group call for chat {chat_id}")
                    except Exception as e:
                        print(f"Error leaving group call: {str(e)}")
                    
                    # Wait a moment before rejoining
                    await asyncio.sleep(2)
                    
                    # Now try to join again
                    try:
                        self.group_calls[chat_id] = await self.call_manager.join_group_call(
                            chat_id,
                            audio_stream
                        )
                        print(f"Successfully rejoined group call for seeking in chat {chat_id}")
                    except Exception as e:
                        if "Already joined into group call" in str(e):
                            print(f"Already in group call, trying to change stream instead")
                            # If we're already in the group call, try to change the stream
                            try:
                                await self.call_manager.change_stream(
                                    chat_id,
                                    audio_stream
                                )
                                print(f"Successfully changed stream for seeking in chat {chat_id}")
                            except Exception as e2:
                                print(f"Error changing stream: {str(e2)}")
                                await wait_message.edit_text(f"Error seeking: {str(e2)}")
                                return
                        else:
                            print(f"Error rejoining group call: {str(e)}")
                            await wait_message.edit_text(f"Error seeking: {str(e)}")
                            return
                
                # Update the playback start time
                if not hasattr(self, 'playback_start_times'):
                    self.playback_start_times = {}
                
                # Set the start time to now (fresh start for the new track)
                self.playback_start_times[chat_id] = time.time()
                
                # Force an update of the control message
                if hasattr(self, 'last_update_times'):
                    self.last_update_times[chat_id] = 0
                
                # Update the control message
                await self.update_control_message(chat_id, True)  # Force update
                
                # Delete the wait message
                try:
                    await wait_message.delete()
                except Exception as e:
                    print(f"Error deleting wait message: {str(e)}")
                
                await message.reply(f"Skipped to: {next_track['title']}")
            except Exception as e:
                print(f"Error changing stream: {str(e)}")
                await wait_message.edit_text(f"Error skipping track: {str(e)}")
                return

    async def refresh_command(self, client: Client, message: Message):
        """Refresh the control message"""
        chat_id = message.chat.id
        
        print(f"Refresh command received for chat {chat_id}")
        
        # Check if there is an active group call
        if not await self.is_group_call_active(chat_id):
            await message.reply("There is no active voice chat.")
            return
            
        # Check if there is a current track
        if chat_id not in self.current_track or not self.current_track[chat_id]:
            await message.reply("No music is currently playing.")
            return
            
        # Create a new control message
        success = await self.create_control_message(chat_id, message)
        
        if success:
            # Start periodic updates if not already running
            if chat_id in self.is_playing and self.is_playing[chat_id]:
                await self.start_periodic_updates(chat_id)
            await message.reply("Control message refreshed.")
        else:
            await message.reply("Failed to refresh control message.")

    async def seek_command(self, client: Client, message: Message):
        """Seek to a specific position in the current track"""
        chat_id = message.chat.id
        
        # Check if there's an active group call
        if not await self.is_group_call_active(chat_id):
            await message.reply("No active call to seek in")
            return
        
        # Check if there's a current track
        if chat_id not in self.current_track or not self.current_track[chat_id]:
            await message.reply("No track is currently playing")
            return
        
        # Check command format
        if len(message.command) != 2:
            await message.reply("Usage: /seek <seconds> - Seeks forward by the specified number of seconds")
            return
        
        try:
            # Parse the seek offset (how many seconds to seek forward)
            seek_offset = int(message.command[1])
            
            # Get the total duration
            total_seconds = None
            if 'duration' in self.current_track[chat_id] and self.current_track[chat_id]['duration']:
                duration_str = self.current_track[chat_id]['duration']
                if isinstance(duration_str, str) and ":" in duration_str:
                    parts = duration_str.split(":")
                    if len(parts) == 2:
                        total_seconds = int(parts[0]) * 60 + int(parts[1])
                    elif len(parts) == 3:
                        total_seconds = int(parts[0]) * 3600 + int(parts[1]) * 60 + int(parts[2])
                elif isinstance(duration_str, (int, float)):
                    total_seconds = int(duration_str)
            
            if total_seconds is None:
                await message.reply("Cannot determine track duration")
                return
            
            # Calculate current position
            current_position = 0
            if hasattr(self, 'playback_start_times') and chat_id in self.playback_start_times:
                current_position = int(time.time() - self.playback_start_times[chat_id])
            
            # Calculate the new position (current + offset)
            seek_seconds = current_position + seek_offset
            
            # Validate the seek position
            if seek_seconds < 0:
                seek_seconds = 0
            elif seek_seconds > total_seconds:
                seek_seconds = total_seconds
            
            # Send a wait message
            wait_message = await message.reply(f"⏩ Seeking forward by {seek_offset} seconds to position {seek_seconds}s...")
            
            # We need to restart the stream to actually seek
            # First, get the current track URL
            track_url = self.current_track[chat_id]['url']
            
            # Create a hash for the original file
            url_hash = hashlib.md5(track_url.encode()).hexdigest()
            
            # Download the original audio file
            original_audio_file = os.path.join(self.download_dir, f"audio_{url_hash}.mp3")
            
            # Create seeked filename that includes the original hash
            seeked_filename = f"seeked_{url_hash}_{seek_seconds}.mp3"
            seeked_audio_file = os.path.join(self.download_dir, seeked_filename)
            
            # Check if the seeked file already exists
            if os.path.exists(seeked_audio_file):
                print(f"Seeked audio file already exists: {seeked_audio_file}")
            else:
                # Use ffmpeg to seek to the desired position
                import subprocess
                
                # Create the ffmpeg command to seek to the desired position
                ffmpeg_cmd = [
                    'ffmpeg',
                    '-y',  # Overwrite output file if it exists
                    '-ss', str(seek_seconds),  # Seek position
                    '-i', original_audio_file,  # Input file
                    '-acodec', 'copy',  # Copy audio codec without re-encoding
                    seeked_audio_file  # Output file
                ]
                
                # Run the ffmpeg command
                process = await asyncio.create_subprocess_exec(
                    *ffmpeg_cmd,
                    stdout=asyncio.subprocess.PIPE,
                    stderr=asyncio.subprocess.PIPE
                )
                
                stdout, stderr = await process.communicate()
                
                if process.returncode != 0:
                    print(f"Error seeking with ffmpeg: {stderr.decode()}")
                    await wait_message.edit_text(f"Error seeking: ffmpeg process failed")
                    return
                
                print(f"Successfully created seeked audio file: {seeked_audio_file}")
            
            # Check if the seeked file exists
            if not os.path.exists(seeked_audio_file):
                print(f"Seeked audio file does not exist: {seeked_audio_file}")
                await wait_message.edit_text(f"Error seeking: seeked file not created")
                return
            
            # Update the current track info with both files and the hash
            self.current_track[chat_id].update({
                'audio_file': seeked_audio_file,
                'original_audio': original_audio_file,
                'file_hash': url_hash
            })
            
            # Now restart the stream
            try:
                # First, make sure we leave any existing group call
                try:
                    # Try to leave the group call using the call manager
                    await self.call_manager.leave_group_call(chat_id)
                    print(f"Successfully left group call for seeking in chat {chat_id}")
                except Exception as e:
                    print(f"Error leaving group call with call_manager: {str(e)}")
                
                # Wait a moment before rejoining
                await asyncio.sleep(2)
                
                # Create an AudioPiped object with AudioParameters
                audio_stream = AudioPiped(
                    seeked_audio_file,
                    AudioParameters(
                        bitrate=48000,
                    ),
                )
                
                # Join the group call again
                try:
                    self.group_calls[chat_id] = await self.call_manager.join_group_call(
                        chat_id,
                        audio_stream
                    )
                    print(f"Successfully rejoined group call for seeking in chat {chat_id}")
                except Exception as e:
                    if "Already joined into group call" in str(e):
                        print(f"Already in group call, trying to change stream instead")
                        # If we're already in the group call, try to change the stream
                        try:
                            await self.call_manager.change_stream(
                                chat_id,
                                audio_stream
                            )
                            print(f"Successfully changed stream for seeking in chat {chat_id}")
                        except Exception as e2:
                            print(f"Error changing stream: {str(e2)}")
                            await wait_message.edit_text(f"Error seeking: {str(e2)}")
                            return
                    else:
                        print(f"Error rejoining group call: {str(e)}")
                        await wait_message.edit_text(f"Error seeking: {str(e)}")
                        return
                
                # Update the playback start time to account for the seek position
                if not hasattr(self, 'playback_start_times'):
                    self.playback_start_times = {}
                # Set the start time to now minus the seek position
                self.playback_start_times[chat_id] = time.time() - seek_seconds
                
                # Force an update of the control message
                if hasattr(self, 'last_update_times'):
                    self.last_update_times[chat_id] = 0
                
                # Update the control message
                await self.update_control_message(chat_id, True)  # Force update
                
                # Delete the wait message
                try:
                    await wait_message.delete()
                except Exception as e:
                    print(f"Error deleting wait message: {str(e)}")
                
                await message.reply(f"✅ Seeked to position {seek_seconds}s")
            except Exception as e:
                print(f"Error changing stream for seeking: {str(e)}")
                await wait_message.edit_text(f"Error seeking: {str(e)}")
                return
        except Exception as e:
            print(f"Error in seek command: {str(e)}")
            await message.reply(f"Error seeking: {str(e)}")
            
            # After successful seeking, clean up the original audio file
            original_audio_file = await self.download_audio(track_url)
            await self.cleanup_audio_file(original_audio_file)
            
            # Update the current track's audio file to the seeked one
            self.current_track[chat_id]['audio_file'] = seeked_audio_file
            
            # Update wait message
            await wait_message.edit_text(f"✅ Seeked to position {seek_seconds}s")
            
            # Update the control message
            await self.update_control_message(chat_id)
            
        except Exception as e:
            print(f"Error in seek command: {str(e)}")
            if 'wait_message' in locals():
                await wait_message.edit_text(f"Error seeking: {str(e)}")
            

if __name__ == "__main__":
    bot = MusicBot()
    bot.run()