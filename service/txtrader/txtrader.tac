from twisted.application import internet, service

from txtrader.webserver import webServerFactory
from txtrader.tcpserver import serverFactory

msvc = service.MultiService()


from os import environ

mode = environ['TXTRADER_MODE']

if mode == 'tws':
  from txtrader.tws import TWS 
  api=TWS()
elif mode == 'rtx':
  from txtrader.rtx import RTX
  api=RTX()
else:
  api = None

internet.TCPServer(api.http_port, webServerFactory(api)).setServiceParent(msvc)
internet.TCPServer(api.tcp_port, serverFactory(api)).setServiceParent(msvc)
application = service.Application('txtrader')
msvc.setServiceParent(application)

