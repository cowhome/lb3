#!/usr/bin/env python3

import logging
import aiohttp

logger = logging.getLogger('trello')

async def create_card(config, name):
    params = {
        "name": name,
        "idList": config['trello']['idea-list'],
        "key":    config['trello']['key'],
        "token":  config['trello']['token']
        }

    async with aiohttp.post('https://api.trello.com/1/cards', params=params) as r:
        if r.status == 200:
            return (None, '\U0001F44D')
        else:
            logger.error("Trello fail %d" % r.status)
            logger.error(await r.text())
        return (None, '\U0001F44E')
