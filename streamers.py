#!/usr/bin/env python3

import logging
import asyncio
import discord

logger = logging.getLogger('streamers')
pending_streamers = {}

async def parse_subunsub_confirm(client, confirm_msg, subscribe):
    user_id = confirm_msg['args']['lb3.user_id'][0]
    message = pending_streamers.pop(user_id, None)
    if message:
        await client.add_reaction(message, '\U0001F5A4')
    # TODO Add role and Trello card

async def add_streamer(message, user_ids):
    # Only respond to one message
    pending_streamers[user_ids[0]] = message

async def remove_streamer(message, user_ids):
    # Only respond to one message
    pending_streamers[user_ids[0]] = message
