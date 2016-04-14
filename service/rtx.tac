from twisted.application import internet, service
from twisted.web import xmlrpc, server

from txtrader.rtx import RTX 
from txtrader.xmlserver import xmlserver
from txtrader.tcpserver import serverFactory
from txtrader.tcpclient import clientFactory 

msvc = service.MultiService()

api=RTX()

xrs = xmlserver(api)
xmlrpc.addIntrospection(xrs)
internet.TCPServer(api.xmlrpc_port, server.Site(xrs)).setServiceParent(msvc)

internet.TCPServer(api.tcp_port, serverFactory(api)).setServiceParent(msvc)

internet.TCPClient(api.api_hostname, api.api_port, clientFactory(api.gateway_connect, 'rtgw')).setServiceParent(msvc)

application = service.Application('txtrader')
msvc.setServiceParent(application)

