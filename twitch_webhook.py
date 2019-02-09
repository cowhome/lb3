#!/usr/bin/env python3

import os
import sys
import json
from urllib.parse import parse_qs, parse_qsl
import hashlib
import hmac
import logging
import ipcqueue.posixmq

# Default just send back OK
response = 'OK\n'

commandline = False
FORMAT = '%(asctime)-15s %(levelname)-5s %(message)s'
if os.getenv("BOTTINGTON_LADY"):
    logging.basicConfig(filename='/var/log/lb3/lady_twitch-webhook.log', level=logging.DEBUG, format=FORMAT)
elif os.getenv("REQUEST_URI"):
    logging.basicConfig(filename='/var/log/lb3/twitch-webhook.log', level=logging.INFO, format=FORMAT)
else:
    logging.basicConfig(level=logging.DEBUG, format=FORMAT)
    commandline = True

def is_id_duplicate(server, new_id):
    notifications_file = '/var/log/lb3/notifications_%s.json' % server
    notifications = []
    try:
        try:
            with open(notifications_file, 'r') as infile:
                notifications = json.load(infile)
        except:
            logging.info("No file yet")

        if new_id in notifications:
            logging.info("Duplicate ID")
            return True

        notifications.append(new_id)
        if len(notifications) > 16:
            notifications.pop(0)
        with open(notifications_file, 'w') as outfile:
            json.dump(notifications, outfile)
    except:
        logging.exception("Duplicate detection baddness")
    return False

try:
    message = None
    args = parse_qs(os.getenv("QUERY_STRING"))
    if not commandline:
        server = args['lb3.server'][0]
        logging.info("server=%s" % server)

    if os.getenv("REQUEST_METHOD") == "GET":
        if 'hub.challenge' in args:
            user_id = args['lb3.user_id'][0]
            logging.info("Response: %s" % args['hub.challenge'])
            logging.info("Mode: %s Topic: %s" % (args['hub.mode'], args['hub.topic']))
            response = args['hub.challenge'][0]
            topic = parse_qsl(args['hub.topic'][0])
            for user in topic:
                if user[0].endswith('user_id'):
                    if user_id == user[1]:
                        message = { 'action':  args['hub.mode'][0],
                                    'args': args }
                    else:
                        logging.error("User ID mismatch: url=%s twitch='%s'" % (user_id, user[1]))
    else:
        input_stdin = sys.stdin.read()
        logging.info("Input: %s" % input_stdin)
        if not commandline:
            sig_input = os.getenv("HTTP_X_HUB_SIGNATURE")
            secret = os.getenv("BOTTINGTON_TWITCH_SECRET")
            logging.info('Signature: %s' % sig_input)
            sig_calc = 'sha256=%s' % hmac.new(secret.encode('utf-8'), msg=input_stdin.encode('utf-8'), digestmod=hashlib.sha256).hexdigest()
        if not commandline and (sig_input != sig_calc):
            logging.debug(input_stdin)
            logging.error('Signature mismatch')
            logging.error('Input: %s' % sig_input)
            logging.error('Input: %s' % sig_calc)
        else:
            input_obj = json.loads(input_stdin)
            if commandline:
                server = input_obj['lb3.server']
                notification_id = sys.argv[1]
            else:
                notification_id = os.getenv("HTTP_TWITCH_NOTIFICATION_ID")
            if notification_id:
                logging.info('Notification: %s' % notification_id)
                if not is_id_duplicate(server, notification_id):
                    message = { 'action': 'stream',
                                'args':   args,
                                'data':   input_obj['data'],
                                'id':     notification_id }
            else:
                logging.info('No notification ID')

    if message:
        mq = ipcqueue.posixmq.Queue('/bottington_%s' % server)
        mq.put(json.dumps(message))
except:
    logging.exception("General baddness")

logging.debug("Final response: '%s'" % response)
print("Content-Type: text/plain")
print("Status: 200 OK")
print()
print(response, end='')
