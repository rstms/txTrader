# txTrader Makefile

REQUIRED_PACKAGES = daemontools-run ucspi-tcp python python-dev
REQUIRED_PIP = pytest Twisted hexdump git+git://github.com/rstms/ultrajson.git simplejson requests pytz tzlocal
PROJECT_PIP = ./dist/*.tar.gz

ENVDIR = /etc/txtrader
PYTHON = python2
PIP = pip2
VENV = $(HOME)/venv/txtrader

# modes: tws cqg rtx
MODE=rtx

TXTRADER_TEST_PORT=51070 
TXTRADER_TEST_HOST=127.0.0.1

default: install

help:
	@echo "\nQuick Start Commands:\n\nsudo make clean && make config && make build && make venv && make install && make run\n"

clean:
	@echo "Cleaning up..."
	rm -f txtrader/*.pyc
	rm -rf build
	rm -rf dist 
	rm -rf $(VENV)
	rm -f etc/txtrader/TXTRADER_VENV
	rm -f .make-*

build:  .make-build

.make-build: .make-config setup.py txtrader/*.py
	@echo "Building..."
	python bumpbuild.py
	python setup.py sdist 
	touch .make-build

config: .make-config

.make-config:
	@echo "Configuring..."
	@getent >/dev/null passwd txtrader && echo "User txtrader exists." || sudo adduser --gecos "" --home / --shell /bin/false --no-create-home --disabled-login txtrader
	@set -e;\
        for package in $(REQUIRED_PACKAGES); do \
	  sudo dpkg -s >/dev/null $$package && echo verified package $$package || (echo missing package $$package; false);\
	done;
	echo $(VENV)>etc/txtrader/TXTRADER_VENV
	sudo mkdir -p $(ENVDIR)
	sudo chmod 770 $(ENVDIR)
	sudo cp -r etc/txtrader/* $(ENVDIR)
	sudo chown -R txtrader.txtrader $(ENVDIR)
	sudo chmod 640 $(ENVDIR)/*
	touch .make-config

testconfig:
	@echo "Configuring test API..."
	sudo sh -c "echo $(TXTRADER_TEST_HOST)>$(ENVDIR)/TXTRADER_API_HOST"
	sudo sh -c "echo $(TXTRADER_TEST_PORT)>$(ENVDIR)/TXTRADER_API_PORT"
	sudo sh -c "echo $(TXTRADER_TEST_ACCOUNT)>$(ENVDIR)/TXTRADER_API_ACCOUNT"
	@echo -n "Restarting service..."
	$(MAKE) restart
	@while [ "$$(txtrader 2>/dev/null $(MODE) status)" != '"Up"' ]; do echo -n '.'; sleep 1; done;
	@txtrader $(MODE) status

cleanup:
	if ps ax | egrep [d]efunct; then \
	  sudo pkill supervise;\
	  sudo pkill multilog;\
	  sudo kill $$(ps fax | awk '/[s]sh -v/{print $$1}');\
	fi
	sleep 3

venv:	.make-venv

.make-venv:
	@echo "(re)configure venv"
	#rm -rf $(VENV)
	virtualenv -p $(PYTHON) $(VENV)
	. $(VENV)/bin/activate; \
	for package in $(REQUIRED_PIP); do \
          echo -n "Installing package $$package into virtual env..."; $(PIP) install --upgrade $$package || false;\
        done;
	touch .make-venv

install: stop_wait build .make-venv config
	@echo "Installing txtrader..."
	. $(VENV)/bin/activate; $(PIP) install --upgrade $(PROJECT_PIP) || false
	sudo cp bin/txtrader /usr/local/bin/txtrader
	sudo mkdir -p /var/svc.d
	if [ -d /var/svc.d/txtrader ]; then\
	  sudo svstat /etc/service/txtrader;\
	else\
	  sudo cp -rp service/txtrader /var/svc.d;\
	  sudo touch /var/svc.d/txtrader/down;\
	  sudo chown -R root.root /var/svc.d/txtrader;\
	  sudo chown root.txtrader /var/svc.d/txtrader;\
	  sudo chown root.txtrader /var/svc.d/txtrader/txtrader.tac;\
	  sudo update-service --add /var/svc.d/txtrader;\
	fi

start:
	@echo "Starting Service..."
	sudo rm -f /etc/service/txtrader/down
	sudo svc -u /etc/service/txtrader
	@while [ "$$(sudo svstat /etc/service/txtrader| awk '{print $$2}')" != 'up' ]; do echo -n '.'; sleep 1; done

start_wait: start
	@echo -n "Waiting for status 'Up'..."
	@while [ "$$(txtrader 2>/dev/null $(MODE) status)" != '"Up"' ]; do echo -n '.'; sleep 1; done;
	@echo "OK"

stop:
	@echo "Stopping Service..."
	if [ -d /etc/service/txtrader ]; then\
	  sudo touch /etc/service/txtrader/down;\
	  ps ax | egrep [t]xtrader.tac && txtrader rtx shutdown "make stop" || echo not running;\
	  sudo svc -d /etc/service/txtrader;\
	  while [ "$$(sudo svstat /etc/service/txtrader| awk '{print $$2}')" != 'down' ]; do echo -n '.'; sleep 1; done;\
	else\
       	  echo service not installed;\
	fi

stop_wait: stop
	@echo -n "Waiting for process termination..."
	@while (ps ax | egrep [t]xtrader.tac >/dev/null); do echo -n '.'; sleep 1; done
	@echo "OK"

restart: stop start
	@echo "Restarting Service..."

uninstall: stop_wait
	@echo "Uninstalling..."
	if [ -e /etc/service/txtrader ]; then\
	  sudo svc -d /etc/service/txtrader;\
	  sudo svc -d /etc/service/txtrader/log;\
	  sudo update-service --remove /var/svc.d/txtrader;\
	fi
	sudo rm -rf /var/svc.d/txtrader
	cat files.txt | xargs rm -f
	sudo rm -f /usr/local/bin/txtrader

TESTS := $(wildcard txtrader/*_test.py)

TPARM := 

.PHONY: test 

test: $(TESTS)
	@echo Testing...
	. $(VENV)/bin/activate && cd txtrader; envdir ../etc/txtrader env TXTRADER_TEST_MODE=$(MODE) py.test -vx $(TPARM) $(notdir $^)

run: 
	@echo Running...
	. $(VENV)/bin/activate && envdir etc/txtrader twistd --reactor=poll --nodaemon --logfile=- --pidfile= --python=service/txtrader/txtrader.tac | tee /tmp/runlog

logorders:
	grep WriteAllClients /tmp/runlog | egrep 'rtx.order' | cut -d'{' -f 2- | xargs -n 1 -d'\n' -iLINE echo "{LINE" | jq .
