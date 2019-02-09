#!/usr/bin/python3

import discord
import ipcqueue.posixmq
import threading
import asyncio
import json
import socket
import logging.handlers
import os
import sys
import datetime
import time
import re

import twitch
import trello
import streamers

# Read config
config_file = sys.argv[1] if len(sys.argv) > 1 else 'lb3-conf.json'
print("What-ho! Bottington here")
print("Getting my papers from '%s'" % config_file)
with open(config_file, 'r') as infile:
    config = json.load(infile)

FORMAT = '%(asctime)-15s %(levelname)-5s %(name)s %(message)s'
if 'log-file' in config:
    print("Logging to %s" % config['log-file'])
    log_handler = logging.handlers.WatchedFileHandler(config['log-file'])
    formatter = logging.Formatter(FORMAT)
    formatter.converter = time.gmtime  # if you want UTC time
    log_handler.setFormatter(formatter)
    logger = logging.getLogger('bottington')
    logger.addHandler(log_handler)
    logger.setLevel(logging.INFO)
else:
    logging.basicConfig(level=logging.DEBUG, format=FORMAT)
    logger = logging.getLogger('bottington')
logger.info("\n\nBottington started at %s\n", datetime.datetime.now())

client = discord.Client()
server = None
config_channels = []
chat_channel_in = None
chat_channel_out = None
commands = {}

async def default_check_message(client, message):
    return False
check_message = default_check_message

class MqReceiveThread (threading.Thread):
    def __init__(self):
        threading.Thread.__init__(self)
        queue_name = '/bottington_%s' % server.id
        self.mq_queue = ipcqueue.posixmq.Queue(queue_name)
        try:
            # Do this to make sure other users can send stuff to us
            os.chmod('/dev/mqueue%s' % queue_name, 0o666)
        except PermissionError:
            logger.warn("Couldn't set permissions on message queue")

    def run(self):
        logger.info("MQ receiving")
        while True:
            message = self.mq_queue.get()
            logger.info("MQ message: '%s'" % message)
            client.loop.call_soon_threadsafe(queue.put_nowait, message)

async def mq_handler_task():
    await client.wait_until_ready()
    logger.info("Waiting for a message")
    while not client.is_closed:
        message = await queue.get()
        logger.info("Queue message: '%s'" % message)
        try:
            message_json = json.loads(message)
            if message_json['action'] == 'stream':
                await twitch.parse_streams(client, config, server, message_json)
            elif message_json['action'] == 'subscribe':
                await streamers.parse_subunsub_confirm(client, message_json, True)
            elif message_json['action'] == 'unsubscribe':
                await streamers.parse_subunsub_confirm(client, message_json, False)
        except:
            logger.exception("Message badness")

async def send_help_message(channel):
    embed=discord.Embed()
    embed.add_field(name='help', value='This help', inline=False)
    embed.add_field(name='add [twitch user] [twitch user]', value='Announce streams for the listed twitch users', inline=False)
    embed.add_field(name='remove [twitch user] [twitch user]', value='Stop announcing streams for the listed twitch users', inline=False)
    embed.add_field(name='announce [twitch user] [twitch user]', value='Announce any current streams for the listed twitch users', inline=False)
    embed.add_field(name='list', value='List Twitch users who will be announced', inline=False)
    embed.add_field(name='resub', value='Resubscribe all currently announced Twitch users', inline=False)
    embed.add_field(name='trello [Some brilliant idea]', value='Add a new card to Trello', inline=False)
    embed.add_field(name='[status|playing|streaming|listening|watching] <status>', value="Set bot's status text", inline=False)
    await client.send_message(channel, content='At your service', embed=embed)

async def set_status(status, text):
    logger.info("Status: %d:%s" % (status, text))
    game = discord.Game(name = text, type = status, url = 'https://www.twitch.tv/communities/jdubzy')
    await client.change_presence(game = game)
    return (None, '\U0001F44D')

async def lb3_add_command(client, message, param_text, params):
    (response, ids) = await twitch.sub_user(config, params)
    if ids:
        await streamers.add_streamer(message, ids)
    return (response, None)

async def lb3_remove_command(client, message, param_text, params):
    (response, ids) = await twitch.unsub_user(config, params)
    if ids:
        await streamers.remove_streamer(message, ids)
    return (response, None)

async def lb3_announce_command(client, message, param_text, params):
    return await twitch.announce_user(client, config, server, params)

async def lb3_list_command(client, message, param_text, params):
    return await twitch.list_subs(client, config)

async def lb3_resub_command(client, message, param_text, params):
    return await twitch.resub(client, config)

async def lb3_trello_command(client, message, param_text, params):
    return await trello.create_card(config, param_text)

async def lb3_status_command(client, message, param_text, params):
    return await set_status(0, param_text)

async def lb3_playing_command(client, message, param_text, params):
    return await set_status(0, param_text)

async def lb3_streaming_command(client, message, param_text, params):
    return await set_status(1, param_text)

async def lb3_listening_command(client, message, param_text, params):
    if params[0] == 'to':
        param_text = param_text.replace('to', '', 1).lstrip()
    return await set_status(2, param_text)

async def lb3_watching_command(client, message, param_text, params):
    return await set_status(3, param_text)

@client.event
async def on_message(message):
    # Only interested in our server
    if message.server != server:
        return

    # we do not want the bot to reply to itself
    if message.author == client.user:
        return

    if message.channel == chat_channel_in:
        await client.send_message(chat_channel_out, message.content)
        return

    bot_user_marker = "<@%s>" % client.user.id
    if bot_user_marker in message.content:
        response = None
        emote = None
        command = message.content.replace(bot_user_marker, '').lstrip()
        elements = command.split()
        command_func = None
        show_help = False
        if message.channel in config_channels:
            show_help = True
            if len(elements) > 0:
                command_func = 'lb3_%s_command' % elements[0]
        elif len(elements) > 0:
            command_func = 'lb3_%s_all_command' % elements[0]
        if command_func and (command_func in commands):
            logging.debug('command=%s' % command)
            logging.debug('elements=%s' % elements)
            logging.debug('command_func=%s' % command_func)
            if command_func in commands:
                show_help = False
                param_text = command.replace(elements[0], '', 1).lstrip()
                (response, emote) = await commands[command_func](client, message, param_text, elements[1:])
        if show_help:
            await send_help_message(message.channel)
            return
        if response:
            if response != "IGNORE":
                await client.send_message(message.channel, response)
        if emote:
            await client.add_reaction(message, emote)
        if not response and not emote and not await check_message(client, message):
            response = "%s %s!" % (config['discord']['greeting'], message.author.mention)
            await client.send_message(message.channel, response)
    else:
        await check_message(client, message)

def find_channels(channel_names):
    channels = []
    for name in channel_names:
        channel = discord.utils.get(server.channels, name = name)
        if channel:
            logger.info("Config channel: %s" % channel)
            channels.append(channel)
    return channels

@client.event
async def on_ready():
    global server
    global config_channels
    global chat_channel_in
    global chat_channel_out
    global check_message
    global commands
    logger.info("Logged in as '%s' '%s''" % (client.user.name, client.user.id))
    if not server:
        for ser in client.servers:
            dconf = config['discord']
            if ser.id == dconf['server']:
                logger.info("Found server '%s' (%s)" % (ser.name, ser.id))
                server = ser
                config_channels = find_channels(dconf['config_channels'])
                if ('chat_channel_in' in dconf) and ('chat_channel_out' in dconf):
                    chat_channel_in = discord.utils.get(server.channels, name = dconf['chat_channel_in'])
                    chat_channel_out = discord.utils.get(server.channels, name = dconf['chat_channel_out'])
                func_re = re.compile(r'lb3_.*_command', re.IGNORECASE)
                for func in globals():
                    if func_re.match(func):
                        logger.info("Found func %s" % func)
                        commands[func] = globals()[func]
                if ('extensions' in dconf):
                    ext_module = __import__(dconf['extensions'])
                    ext_init = getattr(ext_module, 'lb3_extension_init')
                    ext_init(config)
                    check_message = getattr(ext_module, 'check_message')
                    for func in dir(ext_module):
                        if func_re.match(func):
                            logger.info("Found func %s" % func)
                            commands[func] = getattr(ext_module, func)
                mq_thread = MqReceiveThread()
                mq_thread.start()

loop = client.loop
queue = asyncio.Queue(loop = loop)
loop.create_task(mq_handler_task())

client.run(config['discord']['token'])
