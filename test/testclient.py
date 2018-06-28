#!/usr/bin/env python

from os import environ
import sys
import requests
import json


example = """
  Example command:

      envdir /etc/txtrader python testclient.py query_account '{"account": "DEMO1.TEST.DEMO.2"}'

"""

status = 0

hostname = environ['TXTRADER_HOST']
username = environ['TXTRADER_USERNAME']
password = environ['TXTRADER_PASSWORD']
port = environ['TXTRADER_HTTP_PORT']

cmd = sys.argv[1]

if len(sys.argv)>2:
  args = json.loads(sys.argv[2])
else:
  args = None

def url(command):
    return 'http://%s:%s/%s' % (hostname, port, command)

headers = {'Content-type': 'application/json'}
auth=(username, password)

r = requests.get(url(cmd), params=args, headers=headers, auth=auth)

if r.status_code == 200:
    #print(r.text)
    print('%s' % json.dumps(json.loads(r.text),indent=2))
else:
    sys.stderr.write(r.text)
    status = 1

sys.exit(status)
