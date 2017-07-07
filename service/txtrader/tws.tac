from twisted.application import internet, service
from txtrader.tws import TWS 
from txtrader.webserver import webServerFactory
from txtrader.tcpserver import serverFactory

msvc = service.MultiService()
api=TWS()
internet.TCPServer(api.http_port, webServerFactory(api)).setServiceParent(msvc)
internet.TCPServer(api.tcp_port, serverFactory(api)).setServiceParent(msvc)
application = service.Application('txtrader')
msvc.setServiceParent(application)

