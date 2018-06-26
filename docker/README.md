
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

### Client Build

These files will build a docker contaner for the txtrader client code.  A local script `txtrader` will call into the txtrader CLI running in the container.  Provide credentials for the container's SSH connection to the txtrader server for the make command as shown: 

#### Bootstrap Commands:  (These are the commands to use on an AWS Amazon Linux EC2 instance)
```
sudo yum update
sudo yum install jq
sudo yum install docker
sudo usermod -a -G docker ec2-user
sudo service docker start
sudo yum install git
ssh-keygen
cat .ssh/id_rsa.pub
(copy contents of id_rsa.pub to server's ~/.ssh/authorized_hosts file)
git clone https://github.com/rstms/txTrader.git
cd txTrader/docker
make TXTRADER_USER=user TXTRADER_HOST=hostname TXTRADER_KEY=private-key-filename client
sudo make install-scripts
```

#### Quick Start: (see TxTrader README for details)
```
txtrader rtx status
txtrader rtx query_accounts
txtrader rtx query_positions
txtrader rtx help
```
