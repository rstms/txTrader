from twisted.web.xmlrpc import Proxy
from twisted.internet import reactor

from os import environ

def printValue(value):
    print repr(value)
    reactor.stop()

def printError(error):
    print 'error', error
    reactor.stop()


hostname = environ['TXTRADER_HOST']
username = environ['TXTRADER_USERNAME']
password = environ['TXTRADER_PASSWORD']
port = environ['TXTRADER_XMLRPC_PORT']
account = environ['TXTRADER_API_ACCOUNT']

url='http://%s:%s@%s:%s/' % (username, password, hostname, port)
proxy = Proxy(url)

proxy.callRemote('query_account', account).addCallbacks(printValue, printError)
reactor.run()

