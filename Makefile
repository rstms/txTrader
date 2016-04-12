#txTrader Makefile

THIS_FILE := $(lastword $(MAKEFILE_LIST))

REQUIRED_PACKAGES = daemontools-run ucspi-tcp
REQUIRED_PIP = Twisted egenix-mx-base pudb ./dist/*.tar.gz ~/IbPy/dist/*.tar.gz

TXTRADER_PYTHON = /usr/local/lib/python2.7.11/bin/python
TXTRADER_ENVDIR = /etc/txtrader
TXTRADER_VENV = $(HOME)/txtrader-venv

TXTRADER_TEST_HOST = 127.0.0.1
TXTRADER_TEST_PORT = 17496
# set account to AUTO for make testconfig to auto-set demo account
TXTRADER_TEST_ACCOUNT = AUTO

default: 
	@echo "Nothing to do"

clean:
	@echo "Cleaning up..."
	rm -f txtrader/*.pyc
	rm -rf build
	rm -rf $(TXTRADER_VENV)

build:
	@echo "Building..."
	python bumpbuild.py
	python setup.py sdist 

config:
	@echo "Configuring..."
	@getent >/dev/null passwd txtrader && echo "User txtrader exists." || adduser --gecos "" --home / --shell /bin/false --no-create-home --disabled-login txtrader
	@echo $(TXTRADER_VENV)>etc/txtrader/TXTRADER_VENV
	@echo txtrader>etc/txtrader/TXTRADER_DAEMON_USER
	@for package in $(REQUIRED_PACKAGES); do \
	  dpkg-query >/dev/null -l $$package && echo "verified package $$package" || break;\
	done;

testconfig:
	@echo "Configuring test API..."
	$(MAKE) start
	sudo sh -c "echo $(TXTRADER_TEST_HOST)>$(TXTRADER_ENVDIR)/TXTRADER_API_HOST"
	sudo sh -c "echo $(TXTRADER_TEST_PORT)>$(TXTRADER_ENVDIR)/TXTRADER_API_PORT"
	@echo -n "Restarting txTrader service..."
	@sudo svc -t /etc/service/txtrader
	@while ! (txtrader 2>/dev/null tws status); do echo -n .; done
	@if [ "$(TXTRADER_TEST_ACCOUNT)" = "AUTO" ]; then\
	  . $(TXTRADER_VENV)/bin/activate;\
          export ACCOUNT="`envdir /etc/txtrader txtrader tws query_accounts | tr -d []\'`";\
	else\
	  export ACCOUNT="$(TXTRADER_TEST_ACCOUNT)";\
	fi;\
	sudo sh -c "echo $$ACCOUNT>$(TXTRADER_ENVDIR)/TXTRADER_API_ACCOUNT";\
	echo "Set test ACCOUNT=$$ACCOUNT"

install: uninstall config build
	@echo "Installing..."
	virtualenv -p $(TXTRADER_PYTHON) $(TXTRADER_VENV)
	. $(TXTRADER_VENV)/bin/activate; \
	for package in $(REQUIRED_PIP); do \
          echo -n "Installing package $$package into virtual env..."; pip install $$package || false;\
        done;
	cp bin/txtrader /usr/local/bin
	cp -r etc/txtrader $(TXTRADER_ENVDIR)
	chgrp -R txtrader $(TXTRADER_ENVDIR)
	mkdir -p /var/svc.d/txtrader
	cp -r service/* /var/svc.d/txtrader
	touch /var/svc.d/txtrader/down
	update-service --add /var/svc.d/txtrader

start:
	@echo "Starting Service..."
	sudo rm -f /etc/service/txtrader/down
	sudo svc -u /etc/service/txtrader

stop:
	@echo "Stopping Service..."
	sudo touch /etc/service/txtrader/down
	sudo svc -d /etc/service/txtrader

restart: stop start
	@echo "Restarting Service..."
		
uninstall:
	@echo "Uninstalling..."
	if [ -e /etc/service/txtrader ]; then\
	  svc -d /etc/service/txtrader;\
	  svc -d /etc/service/txtrader/log;\
	  update-service --remove /var/svc.d/txtrader;\
	fi
	rm -rf /var/svc.d/txtrader
	rm -rf $(TXTRADER_ENVDIR)
	cat files.txt | xargs rm -f
	rm -f /usr/local/bin/txtrader

TESTS := $(wildcard txtrader/test-*.py)

test: $(TESTS)
	@echo "Testing..."
	cd txtrader; envdir ../etc/txtrader py.test -vvx $(notdir $^)
