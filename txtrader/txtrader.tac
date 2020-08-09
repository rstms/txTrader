from twisted.application import internet, service

from txtrader.webserver import webServerFactory
from txtrader.tcpserver import serverFactory
from txtrader.rtx import RTX

msvc = service.MultiService()

api=RTX()

internet.TCPServer(api.http_port, webServerFactory(api)).setServiceParent(msvc)
internet.TCPServer(api.tcp_port, serverFactory(api)).setServiceParent(msvc)
application = service.Application('txtrader')
msvc.setServiceParent(application)

