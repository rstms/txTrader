# ibgw

default:
	@cat README.md

server: build start 

client: build-client start-client 

stop:	stop-client stop-server

start:  start-server start-client

build:
	-rm -rf txtrader/keys
	mkdir txtrader/keys
	cp $(HOME)/.ssh/id_rsa.pub txtrader/keys/public_key
	#cp $(HOME)/.ssh/github-rsstools-deploy txtrader/keys
	docker build --tag txtrader txtrader 
	rm -rf txtrader/keys

check-user:
	@[ -n "$$TXTRADER_USER" ] || (echo set TXTRADER_USER to the username for the ssh connection to the txtrader server && false)

check-host:
	@[ -n "$$TXTRADER_HOST" ] || (echo set TXTRADER_HOST to the hostname of the txtrader server && false)

check-key:
	@[ -f "$$TXTRADER_KEY" ] || (echo TXTRADER_KEY must the private key pathname for the ssh connection to the txtrader server && false)

build-client: check-user check-host check-key
	-rm -rf txclient/keys
	mkdir txclient/keys
	cp $(HOME)/.ssh/id_rsa.pub txclient/keys/public_key
	cp $(TXTRADER_KEY) txclient/keys/server_key
	@echo $(TXTRADER_USER) >>txclient/keys/server_user
	@echo $(TXTRADER_HOST) >>txclient/keys/server_host
	docker build --tag txclient txclient 
	rm -rf txclient/keys

start-client:
	@if [ -z "$$(docker ps -aqf Name=txclient)" ]; then \
	  HOST_IP=`ifconfig eth0 | awk '/inet addr/{print $$2}' | awk -F: '{print $$2}'` && \
	  docker run --restart always --detach --name=txclient txclient:latest && \
	  docker ps;\
	else \
	  echo "Already started."; \
	fi

stop-client:
	@for BOX in `docker ps -aqf Name=txclient`; do \
	  docker rm -f $$BOX;\
	done;

start-server:
	@if [ -z "$$(docker ps -aqf Name=txtrader)" ]; then \
	  HOST_IP=`ifconfig eth0 | awk '/inet addr/{print $$2}' | awk -F: '{print $$2}'` && \
	  docker run --restart always --detach -p 50070:50070 -p 50090:50090 --add-host="ibgw:$$HOST_IP" --name=txtrader txtrader:latest && \
	  docker ps;\
	else \
	  echo "Already started."; \
	fi
 
start-txtrader:
	ssh.txtrader "cd /home/txtrader/txTrader && make start-tws"

stop-txtrader:
	ssh.txtrader "cd /home/txtrader/txTrader && make stop-tws"

stop-server: 
	@for BOX in `docker ps -aqf Name=txtrader`; do \
	  docker rm -f $$BOX;\
	done;

clean: stop
	docker rm -f $$(docker ps -aq)
	docker rmi -f $$(docker images -aq)

install-scripts:
	cp scripts/* /usr/local/bin
	keygen.txclient
	keygen.txtrader
