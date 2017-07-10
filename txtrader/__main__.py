from twisted.application import internet, service
from twisted.internet import reactor

from txtrader.tws import TWS 
from txtrader.tcpserver import serverFactory
from txtrader.webserver import webServerFactory

msvc = service.MultiService()

api=TWS()
internet.TCPServer(api.http_port, webServerFactory(api)).setServiceParent(msvc)
internet.TCPServer(api.tcp_port, serverFactory(api)).setServiceParent(msvc)
application = service.Application('txtrader')
msvc.setServiceParent(application)
reactor.run()
