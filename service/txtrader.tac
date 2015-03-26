from twisted.application import internet, service
from twisted.web import xmlrpc, server

from txtrader.tws import TWS 
from txtrader.xmlserver import xmlserver
from txtrader.tcpserver import serverFactory

msvc = service.MultiService()

api=TWS()

xrs = xmlserver(api)
xmlrpc.addIntrospection(xrs)
internet.TCPServer(api.xmlrpc_port, server.Site(xrs)).setServiceParent(msvc)

internet.TCPServer(api.tcp_port, serverFactory(api)).setServiceParent(msvc)

application = service.Application('txtrader')

msvc.setServiceParent(application)

