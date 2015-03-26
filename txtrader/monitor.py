# txTrader  receiver.py
# stand alone status receiver

# Copyright (c) 2015 Reliance Systems, Inc.


from twisted.internet import reactor, protocol

class Monitor():
  def __init__(self, host='localhost', port=50090, user=None, password=None, on_status=None, on_order=None, on_execution=None, on_quote=None, on_trade=None):
    self.host = host
    self.port = port
    self.user = user
    self.password = password
    self.on_status = on_status if on_status else self._on_status
    self.on_order = on_order if on_order else self._on_order
    self.on_execution = on_execution if on_execution else self._on_execution
    self.on_quote = on_quote if on_quote else self._on_quote
    self.on_trade = on_trade if on_trade else self._on_trade

  def listen(self, _reactor):
    f = StatusClientFactory(self)
    reactor.connectTCP(self.host, self.port, f)

  def _handler(self, label, msg):
    print('%s: %s' % (label, repr(msg)))

  def _on_status(self, msg):
    self._handler('status', msg)

  def _on_order(self, msg):
    self._handler('order', msg)
 
  def _on_execution(self, msg):
    self._handler('execution', msg)
 
  def _on_trade(self, msg):
    self._handler('trade', msg)
 
  def _on_quote(self, msg):
    self._handler('quote', msg)
 

  def run(self):
    self.listen(reactor)
    reactor.run()


class StatusClient(protocol.Protocol):
    
    def connectionMade(self):
        print 'connected'
    
    def dataReceived(self, data):
        self.factory.rx.on_status(data)
        if data.startswith('.connected'):
          self.transport.write('auth %s %s\n' % (self.factory.rx.user, self.factory.rx.password))
  
        #self.transport.loseConnection()
    
    def connectionLost(self, reason):
        print 'connection lost'

class StatusClientFactory(protocol.ClientFactory):
    protocol = StatusClient 
    def __init__(self, receiver):
        self.rx = receiver

    def clientConnectionFailed(self, connector, reason):
        print "Connection failed - goodbye!"
        reactor.stop()
    
    def clientConnectionLost(self, connector, reason):
        print "Connection lost - goodbye!"
        reactor.stop()


if __name__ == '__main__':

  _USER = 'gravitar'
  _PASS = '2GPB1FYDG9dts'
  rx = Monitor(user=_USER, password=_PASS)
  rx.run()
