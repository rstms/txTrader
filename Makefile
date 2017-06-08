#txTrader Makefile

THIS_FILE := $(lastword $(MAKEFILE_LIST))

REQUIRED_PACKAGES = daemontools-run ucspi-tcp
REQUIRED_PIP = Twisted egenix-mx-base pudb ./dist/*.tar.gz ~/IbPy/dist/*.tar.gz

TXTRADER_PYTHON = /usr/bin/python2
TXTRADER_ENVDIR = /etc/txtrader
TXTRADER_VENV = $(HOME)/txtrader-venv

TXTRADER_MODE = rtx

# set account to AUTO for make testconfig to auto-set demo account
TXTRADER_TEST_MODE = RTX
TXTRADER_TEST_HOST = 127.0.0.1
TXTRADER_TEST_PORT = 51070
TXTRADER_TEST_ACCOUNT = AUTO

default:
	@echo "\nQuick Start Commands:\n\nsudo make config; make build; sudo make -e TXTRADER_MODE=tws install; sudo make -e TXTRADER_MODE=rtx install\n"

clean:
	@echo "Cleaning up..."
	rm -f txtrader/*.pyc
	rm -rf build
	rm -rf $(TXTRADER_VENV)
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
	@getent >/dev/null passwd txtrader && echo "User txtrader exists." || adduser --gecos "" --home / --shell /bin/false --no-create-home --disabled-login txtrader
	@echo $(TXTRADER_VENV)>etc/txtrader/TXTRADER_VENV
	@echo txtrader>etc/txtrader/TXTRADER_DAEMON_USER
	@for package in $(REQUIRED_PACKAGES); do \
	  dpkg-query >/dev/null -l $$package && echo "verified package $$package" || break;\
	done;
	mkdir -p /etc/txtrader
	chmod 770 $(TXTRADER_ENVDIR)
	cp -r etc/txtrader/* $(TXTRADER_ENVDIR)
	chown -R txtrader.txtrader $(TXTRADER_ENVDIR)
	chmod 640 $(TXTRADER_ENVDIR)/*
	touch .make-config

testconfig:
	@echo "Configuring test API..."
	$(MAKE) start
	sudo sh -c "echo $(TXTRADER_TEST_PORT)>$(TXTRADER_ENVDIR)/TXTRADER_$(TXTRADER_TEST_MODE)_API_PORT"
	sudo sh -c "echo $(TXTRADER_TEST_ACCOUNT)>$(TXTRADER_ENVDIR)/TXTRADER_$(TXTRADER_TEST_MODE)_API_ACCOUNT"
	@echo -n "Restarting service..."
	@sudo svc -t /etc/service/txtrader.$(TXTRADER_MODE)
	@while [ "$$(txtrader 2>/dev/null rtx status)" != "Connected" ]; do echo -n .;sleep 1; done;
	@txtrader $(TXTRADER_MODE) status
	@if [ "$(TXTRADER_TEST_ACCOUNT)" = "AUTO" ]; then\
          echo -n "Getting account...";\
	  while [ "$$(txtrader 2>/dev/null rtx query_accounts)" = "[]" ]; do echo -n .;sleep 1; done;\
	  echo OK;\
	  export ACCOUNT="`txtrader $(TXTRADER_MODE) query_accounts | tr -d \"[]\'\" | cut -d, -f1`";\
	else\
	  export ACCOUNT="$(TXTRADER_TEST_ACCOUNT)";\
	fi;\
	echo "Setting test ACCOUNT=$$ACCOUNT";\
	sudo sh -c "echo $$ACCOUNT>$(TXTRADER_ENVDIR)/TXTRADER_$(TXTRADER_TEST_MODE)_API_ACCOUNT";\

.make-venv: .make-build
	rm -rf $(TXTRADER_VENV)
	virtualenv -p $(TXTRADER_PYTHON) $(TXTRADER_VENV)
	. $(TXTRADER_VENV)/bin/activate; \
	for package in $(REQUIRED_PIP); do \
          echo -n "Installing package $$package into virtual env..."; pip install $$package || false;\
        done;
	touch .make-venv

install-tws:
	$(MAKE) TXTRADER_MODE=tws install

install-rtx:
	$(MAKE) TXTRADER_MODE=rtx install

install: .make-venv config
	@echo "Installing txtrader.$(TXTRADER_MODE)..."
	cp bin/txtrader /usr/local/bin
	rm -rf /var/svc.d/txtrader.$(TXTRADER_MODE)
	cp -rp service/txtrader.$(TXTRADER_MODE) /var/svc.d
	touch /var/svc.d/txtrader.$(TXTRADER_MODE)/down
	chown -R root.root /var/svc.d/txtrader.$(TXTRADER_MODE)
	chown root.txtrader /var/svc.d/txtrader.$(TXTRADER_MODE)
	chown root.txtrader /var/svc.d/txtrader.$(TXTRADER_MODE)/*.tac
	update-service --add /var/svc.d/txtrader.$(TXTRADER_MODE)

start-tws:
	$(MAKE) TXTRADER_MODE=tws start 

start-rtx:
	$(MAKE) TXTRADER_MODE=rtx start 

start:
	@echo "Starting Service..."
	sudo rm -f /etc/service/txtrader.$(TXTRADER_MODE)/down
	sudo svc -u /etc/service/txtrader.$(TXTRADER_MODE)

stop-tws:
	$(MAKE) TXTRADER_MODE=tws stop

stop-rtx:
	$(MAKE) TXTRADER_MODE=rtx stop

stop:
	@echo "Stopping Service..."
	sudo touch /etc/service/txtrader.$(TXTRADER_MODE)/down
	sudo svc -d /etc/service/txtrader.$(TXTRADER_MODE)

restart: stop start
	@echo "Restarting Service..."

uninstall-tws:
	$(MAKE) TXTRADER_MODE=tws uninstall
		
uninstall-rtx:
	$(MAKE) TXTRADER_MODE=rtx uninstall
		
uninstall:
	@echo "Uninstalling..."
	if [ -e /etc/service/txtrader.$(TXTRADER_MODE) ]; then\
	  svc -d /etc/service/txtrader.$(TXTRADER_MODE);\
	  svc -d /etc/service/txtrader.$(TXTRADER_MODE)/log;\
	  update-service --remove /var/svc.d/txtrader.$(TXTRADER_MODE);\
	fi
	rm -rf /var/svc.d/txtrader.$(TXTRADER_MODE)
	cat files.txt | xargs rm -f
	rm -f /usr/local/bin/txtrader

TESTS := $(wildcard txtrader/test-*.py)

TPARM := -vvvs

.PHONY: test 

test: $(TESTS)
	@echo "Testing..."
	cd txtrader; envdir ../etc/txtrader py.test $(TPARM) $(notdir $^)

testserver: 
	envdir etc/txtrader txtrader/rtx.py
