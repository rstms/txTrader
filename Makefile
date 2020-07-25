# txTrader makefile
#

build: fmt
	docker-compose build 

# run the service locally
run:
	docker-compose run --rm --service-ports txtrader | tee log

# start the service locally in the background
start:
	docker-compose up --build -d txtrader

# stop the local running service
stop:
	docker-compose down 

# stop and restart the local running service
restart: stop start

# run the regression tests
TPARM?=-svx
test: build
	docker-compose run --rm txtrader /bin/bash -c 'pytest ${TPARM} ${TESTS}'

# start a shell in the container with the dev directory bind-mounted
shell:
	docker-compose run --rm --service-ports -v $$(pwd)/txtrader:/home/txtrader/txtrader txtrader /bin/bash -l

debug: build
	docker-compose run --rm --service-ports -v $$(pwd)/txtrader:/home/txtrader/txtrader txtrader /bin/bash -l -c "txtraderd --debug"

monitor:
	docker-compose run -e TXTRADER_HOST txtrader bash -l -c txtrader_monitor

# tail the log of any running txtrader container
tail:
	while true; do (docker ps -q --filter name=txtrader | xargs -r docker logs --follow); sleep 3; done

# yapf format all changed python sources
fmt: .fmt
.fmt: $(shell find . -type f | grep \.py$$)
	@$(foreach s,$?,yapf -i -vv ${s};)
	@touch $@

