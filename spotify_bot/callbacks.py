from pyrogram import Client, filters
from pyrogram.types import CallbackQuery, InlineKeyboardButton, InlineKeyboardMarkup
import time
import asyncio
import os
import hashlib
from pytgcalls.types import AudioPiped
from pytgcalls.types.input_stream.quality import HighQualityAudio
from pytgcalls.types import AudioParameters
from spotify_bot.helpers import format_duration
from .helpers import format_duration

# Define callback data prefixes
PAUSE_CB = "pause"
RESUME_CB = "resume"
STOP_CB = "stop"
CLOSE_CB = "close"
NEXT_CB = "next"
PLAYPAUSE_CB = "playpause"

def get_music_control_keyboard(is_playing=True, has_queue=False):
    keyboard = [
        [
            InlineKeyboardButton("⏸️ Pause" if is_playing else "▶️ Resume", callback_data=PLAYPAUSE_CB),
            InlineKeyboardButton("⏭️ Next", callback_data=NEXT_CB)  # Always show "Next"
        ],
        [
            InlineKeyboardButton("⏹️ Stop", callback_data=STOP_CB)
        ]
    ]

    return InlineKeyboardMarkup(keyboard)

def register_callbacks(bot):
    """
    Register callback query handlers for the bot
    """
    @bot.app.on_callback_query(filters.regex(f"^{PLAYPAUSE_CB}"))
    async def playpause_callback(client, callback_query: CallbackQuery):
        """Handle play/pause button callback"""
        chat_id = callback_query.message.chat.id
        
        # Get the bot instance
        bot_instance = bot
        
        # Check if there's an active group call
        is_active = await bot_instance.is_group_call_active(chat_id)
        is_playing = bot_instance.is_playing.get(chat_id, False)
        
        if is_active or bot_instance.active_calls.get(chat_id, False):
            if is_playing:
                # Call the pause method
                await bot_instance.pause_stream(chat_id)
                await callback_query.answer("Music paused")
            else:
                # Call the resume method
                await bot_instance.resume_stream(chat_id)
                await callback_query.answer("Music resumed")
            
            # Update the keyboard (seek buttons removed)
            has_queue = chat_id in bot_instance.queue and len(bot_instance.queue[chat_id]) > 0
            new_keyboard = get_music_control_keyboard(is_playing=not is_playing, has_queue=has_queue)
            
            try:
                await callback_query.message.edit_reply_markup(new_keyboard)
            except Exception as e:
                print(f"Error updating keyboard: {str(e)}")
        else:
            await callback_query.answer("Nothing is playing")

    
    @bot.app.on_callback_query(filters.regex(f"^{STOP_CB}"))
    async def stop_callback(client, callback_query: CallbackQuery):
        """Handle stop button callback"""
        chat_id = callback_query.message.chat.id
        user_id = callback_query.from_user.id
        
        # Get the bot instance
        bot_instance = bot  # Use the bot parameter directly
        
        # Check if there's an active group call
        is_active = await bot_instance.is_group_call_active(chat_id)
        
        if is_active or bot_instance.active_calls.get(chat_id, False) or bot_instance.is_playing.get(chat_id, False):
            # Send a wait message
            wait_message = await callback_query.message.reply("⏹️ Stopping music... Please wait.")
            
            # Call the stop method
            await bot_instance.stop_streaming(chat_id)
            
            # Delete wait message
            try:
                await wait_message.delete()
            except Exception as e:
                print(f"Error deleting wait message: {str(e)}")
                
            await callback_query.answer("Stopped the music")
            
            # Try to delete the message with the controls
            try:
                await callback_query.message.delete()
            except Exception as e:
                print(f"Error deleting message: {str(e)}")
        else:
            await callback_query.answer("Nothing is playing")

    @bot.app.on_callback_query(filters.regex(f"^{NEXT_CB}"))
    async def next_callback(client, callback_query: CallbackQuery):
        """Handle next button callback"""
        chat_id = callback_query.message.chat.id
        bot_instance = bot  # Use the bot instance

        # Check if there are songs in the queue
        has_queue = chat_id in bot_instance.queue and len(bot_instance.queue[chat_id]) > 0

        if has_queue:
            wait_message = await callback_query.message.reply("⏭️ Skipping to next track... Please wait.")
            try:
                await bot_instance.skip_track(callback_query.message)
                await callback_query.answer("Skipping to next track")
            except Exception as e:
                print(f"Error in next callback: {str(e)}")
                await wait_message.delete()
                await callback_query.answer("Error skipping track")
        else:
            await callback_query.answer("No songs in the queue", show_alert=True)
    
    @bot.app.on_callback_query(filters.regex(f"^{CLOSE_CB}"))
    async def close_callback(client, callback_query: CallbackQuery):
        """Handle close button callback"""
        chat_id = callback_query.message.chat.id
        user_id = callback_query.from_user.id
        
        # Delete the message with the controls
        try:
            await callback_query.message.delete()
            await callback_query.answer("Player controls closed")
        except Exception as e:
            print(f"Error deleting message: {str(e)}")
            await callback_query.answer("Failed to close player controls")
