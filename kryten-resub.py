#!/usr/bin/env python3

import requests
import json
import sys

# Read config
config_file = sys.argv[1] if len(sys.argv) > 1 else 'lb3-conf.json'
with open(config_file, 'r') as infile:
    config = json.load(infile)

data = { 'username': 'Kryten', 'content':   "<@%s> resub" % config['discord']['client-id'] }
headers = { 'Content-Type': 'application/json' }
r = requests.post(config['kryten-webhook'], headers=headers, data=json.dumps(data))
if r.status_code != 204:
    print('Discord HTTP %d' % r.status_code)
    print(r.text)
