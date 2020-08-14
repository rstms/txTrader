from twisted.application import internet, service
from twisted.internet import reactor

from txtrader.tcpserver import serverFactory
from txtrader.webserver import webServerFactory

from txtrader.rtx import RTX


def main():
    msvc = service.MultiService()

    api = RTX()
    internet.TCPServer(api.http_port, webServerFactory(api)).setServiceParent(msvc)
    internet.TCPServer(api.tcp_port, serverFactory(api)).setServiceParent(msvc)
    application = service.Application('txtrader')
    msvc.setServiceParent(application)
    reactor.run()


if __name__ == '__main__':
    main()
