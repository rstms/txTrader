
TxTrader containers
-------------------

These containers may be used to run the server, client or both.  The server machine can run an IB client as well 
as the txTrader server.  The client container maintains an SSH session securing the client's connection to txTrader.

### Requirements:

 - docker
 - make
 - bash
 - [jq](https://stedolan.github.io/jq)


### Server Build
```
make server
sudo make install-scripts
```

## Client Build

These files will build a docker contaner for the txtrader client code.  A local script `txtrader` will call into the txtrader CLI running in the container.  Provide credentials for the container's SSH connection to the txtrader server for the make command as shown: 

Commands:
```
make TXTRADER_USER=user TXTRADER_HOST=hostname TXTRADER_KEY=private-key-filename client
sudo make install-scripts
```

Operation: (see TxTrader README for details)
```
txtrader rtx status

txtrader rtx query_accounts

txtrader rtx help
```
