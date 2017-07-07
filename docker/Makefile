# ibgw

build:
	-rm -rf txtrader/keys
	mkdir txtrader/keys
	cp $(HOME)/.ssh/id_rsa.pub txtrader/keys/public_key
	cp $(HOME)/.ssh/github-rsstools-deploy txtrader/keys
	docker build --tag txtrader txtrader 
	rm -rf txtrader/keys

start:
	@if [ -z "$$(docker ps -aqf Name=txtrader)" ]; then \
	  HOST_IP=`ifconfig eth0 | awk '/inet addr/{print $$2}' | awk -F: '{print $$2}'` && \
	  docker run --restart always --detach -p 50080:50080 -p 50090:50090 --add-host="ibgw:$$HOST_IP" --name=txtrader txtrader:latest && \
	  docker ps;\
	else \
	  echo "Already started."; \
	fi
 
start-txtrader:
	ssh.txtrader "cd /home/txtrader/txTrader && make start-tws"

stop-txtrader:
	ssh.txtrader "cd /home/txtrader/txTrader && make stop-tws"

stop: 
	@for BOX in `docker ps -aqf Name=txtrader`; do \
	  docker rm -f $$BOX;\
	done;

clean:
	docker rmi -f $$(docker images -aq)
	docker rm $$(docker ps -aq)

install-scripts:
	cp scripts/* /usr/local/bin
