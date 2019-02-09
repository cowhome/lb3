#!/usr/bin/env python3

import os
import sys
import json
import dateutil.parser
import datetime
import pytz
import logging
import aiohttp
import discord

logger = logging.getLogger('twitch')
stream_state = {}

async def twitch_request(client_id, endpoint, in_id):
    params = { 'id': in_id }
    headers = { 'Client-ID': client_id }
    try:
        async with aiohttp.get('https://api.twitch.tv/helix/%s' % endpoint, headers=headers, params=params) as r:
            if r.status == 200:
                js = await r.json()
                return js['data'][0]
            else:
                logger.error('Twitch HTTP badness: %s', r.status)
                logger.error(await r.text())
    except:
        logger.error('Twitch baddness')
    return None

async def get_user(client_id, user_id):
    return await twitch_request(client_id, 'users', user_id)

async def get_game_title(client_id, game_id, user_id):
    game = await twitch_request(client_id, 'games', game_id)
    if game:
        return game['name']
    else:
        headers = { 'Client-ID': client_id,
                    'Accept':    'application/vnd.twitchtv.v5+json' }
        try:
            async with aiohttp.get('https://api.twitch.tv/kraken/streams/%s' % user_id, headers=headers) as r:
                if r.status == 200:
                    js = await r.json()
                    game_name = ['stream']['game']
                    if game_name == "":
                        game_name = 'Playing some videogames'
                    return game_name
                else:
                    logger.error('Twitch Kraken HTTP badness: %s', r.status)
                    logger.error(await r.text())
        except:
            logger.error('Twitch Kraken baddness')
        return 'Playing some videogames'

async def lookup_users(config, user_list):
    headers = { 'Client-ID': config['twitch']['client-id'],
                'Content-Type': 'application/json' }
    async with aiohttp.get('https://api.twitch.tv/helix/users', headers=headers, params=user_list) as r:
        if r.status == 200:
            user_json = await r.json()
            return user_json['data']
        else:
            logger.error("Username look-up fail %d" % r.status)
            logger.error(await r.text())
    return []

def ibzytime(hour, minute):
    negative = False
    hm = (hour * 60) + minute
    if (hour < 11):
        hm += (24 * 60)
    hm -= (23 * 60)
    if (hm < 0):
        hm *= -1
        negative = True
    return '%s%02d:%02d EIT' % ('-' if negative else '+', (hm / 60), (hm % 60))

async def parse_streams(client, config, server, stream_data):
    users_announced = []
    try:
        client_id = config['twitch']['client-id']
        for live_data in stream_data['data']:
            logger.debug(live_data)
            if ('type' in live_data) and (live_data['type'] != 'live'):
                logger.info('Ignoring VOD')
                continue
            # Was seeing some issues where the first notification had no language set, and then the second was sent
            # with a different ID.  Looks like Twitch may have fixed this, so commenting to prevent notifications
            # being ignored.
            #if ('language' in live_data) and (live_data['language'] == ''):
            #   logger.info("Ignoring live data with no language set")
            #   continue
            start_time = dateutil.parser.parse(live_data['started_at'])
            ourtz = pytz.timezone('Europe/London')
            time_now = datetime.datetime.utcnow().replace(tzinfo=pytz.utc)
            start_time_local = start_time.astimezone(ourtz)
            time_diff = time_now - start_time
            logger.info("Started %d:%02d Delay %s" % (start_time_local.hour, start_time_local.minute, time_diff))
            user_id = live_data['user_id']
            user = await get_user(client_id, user_id)
            last_stream = None
            if user_id in stream_state:
                last_stream = stream_state[user_id]

            game_title = await get_game_title(client_id, live_data['game_id'], user_id)
            user_url = "https://twitch.tv/%s" % user['login']
            embed = discord.Embed(title = user_url, url = user_url, color = 2207743)
            embed.set_author(name = "I say, %s has gone live!" % user['display_name'], url = user_url) 
            embed.set_thumbnail(url = user['profile_image_url'])  
            embed.add_field(name = game_title, value = live_data['title'], inline = False)
            if user['login'] == 'evenibzy':
                embed.set_footer(text = ("Stream started %s" % ibzytime(start_time_local.hour, start_time_local.minute)))
            else:
                embed.set_footer(text = ("Stream started %d:%02d" % (start_time_local.hour, start_time_local.minute)))

            channels = config['discord']['channels']
            channel_name = channels['_default_']
            delete = True
            if user['login'] in channels:
                channel_name = channels[user['login']]
                delete = False
            logger.debug("channel_name=%s" % channel_name)
            channel = discord.utils.get(server.channels, name = channel_name)
            try:
                new_stream = {}
                new_stream['message'] = await client.send_message(channel, embed = embed)
                stream_state[user_id] = new_stream
                users_announced.append(user['display_name'])
                logger.debug('Sent %s:%s' % (user['login'], new_stream['message'].id))
                if last_stream and delete:
                    logger.debug('Deleting %s:%s' % (user['login'], last_stream['message'].id))
                    try:
                        await client.delete_message(last_stream['message'])
                    except:
                        logger.exception('Delete failed')
                elif not delete:
                    logger.debug('No delete on this stream')
                else:
                    logger.debug('No prior stream to delete')
            except:
                logger.exception('Discord badness')
                logger.error("channel_name=%s" % channel_name)
                logger.error("embed=%s" % embed.to_dict())
    except:
        logger.exception('Stream badness')
    return users_announced

async def sub_unsub_user(config, user_logins, subscribe, users = None):
    headers = { 'Client-ID': config['twitch']['client-id'],
                'Content-Type': 'application/json' }

    # Post data for subscription request
    sub_data = { "hub.mode":          "subscribe" if subscribe else "unsubscribe",
                 "hub.lease_seconds": 864000,
                 "hub.secret":        config['twitch']['secret']
               }
    if not users:
        users = await lookup_users(config, list(map(lambda u: ('login', u), user_logins)))
    user_names = ''
    user_ids = []
    # Send a (un)subcription request for each username
    for user in users:
        logger.info('%s: %s' % (user['display_name'], user['id']))
        sub_data['hub.callback'] = "%s?lb3.server=%s&lb3.user_id=%s" % (config['twitch']['webhook_uri'], config['discord']['server'], user['id'])
        sub_data['hub.topic'] = "https://api.twitch.tv/helix/streams?user_id=%s" % user['id']
        # Send a (un)subcription request for each username
        async with aiohttp.post('https://api.twitch.tv/helix/webhooks/hub', headers=headers, data=json.dumps(sub_data)) as r:
            if r.status== 202:
                logger.info('%s OK' % sub_data['hub.topic'])
                user_names += ' %s' % user['display_name']
                user_ids.append(user['id'])
            else:
                logger.error('Went wrong %d' % r.status)
                logger.error(await r.text())
    if len(user_ids) > 0:
        if subscribe:
            return ("Right-ho, I've asked those lovely chaps at Twitch to tell me when**%s** goes live" % user_names, user_ids)
        else:
            return ("Right-ho, I've asked those lovely chaps at Twitch stop telling me about**%s**" % user_names, user_ids)
    return ("Sorry, old-bean. I couldn't find anyone.", None)

async def sub_user(config, user_logins):
    return await sub_unsub_user(config, user_logins, True)

async def unsub_user(config, user_logins):
    return await sub_unsub_user(config, user_logins, False)

async def announce_user(client, config, server, user_logins):
    response = "Nothing doing, I'm afraid"
    logger.info(user_logins)
    headers = { 'Client-ID': config['twitch']['client-id'],
                'Content-Type': 'application/json' }
    params = list(map(lambda u: ('user_login', u), user_logins))

    async with aiohttp.get('https://api.twitch.tv/helix/streams', headers=headers, params=params) as r:
        if r.status == 200:
            streams_json = await r.json()
            users = await parse_streams(client, config, server, streams_json)
            if len(users) > 0:
                response = "Announced %s" % (' '.join(users))
    return (response, None)

async def get_subs(config):
    headers = { 'Authorization': 'Bearer %s' % config['twitch']['app-token'] }
    get_more = True
    user_ids = []
    params = None
    while get_more:
        get_more = False
        async with aiohttp.get('https://api.twitch.tv/helix/webhooks/subscriptions', headers=headers, params=params) as r:
            if r.status == 200:
                subs = await r.json()
                logger.debug("All subs: %s" % subs)
                server_str = 'lb3.server=%s' % config['discord']['server']
                server_subs = list(filter(lambda sub: server_str in sub['callback'], subs['data']))
                logger.debug("Server subs: %s" % server_subs)
                new_ids = list(map(lambda sub: ('id', sub['topic'].split('=')[1]), server_subs))
                logger.debug("User IDs: %s" % new_ids)
                user_ids.extend(new_ids)
                if ('pagination' in subs) and ('cursor' in subs['pagination']):
                    params = [('after', subs['pagination']['cursor'])]
                    get_more = True

            else:
                logger.error('Twitch webhook HTTP badness: %s', r.status)
                logger.error(await r.text())

    if len(user_ids) > 0:
        return await lookup_users(config, user_ids)
    return None

async def list_subs(client, config):
    users = await get_subs(config)
    if users:
        logger.debug("Users: %s" % users)
        user_names = list(map(lambda user: user['display_name'], users))
        return ("Twitch will tell me about **%s**" % ' '.join(user_names), None)
    else:
        return ("Sorry, I can't seem to find my notes", None)

async def resub(client, config):
    users = await get_subs(config)
    if users:
        logger.debug("Users: %s" % users)
        return await sub_unsub_user(config, None, True, users)
    else:
        return ("I appear to have lost my users", None)
