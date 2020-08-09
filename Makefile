# pypi deploy Makefile

ORG:=rstms
PROJECT:=$(shell basename `pwd` | tr - _ | tr [A-Z] [a-z])
PROJECT_NAME:=$(shell basename `pwd` | tr [A-Z] [a-z])

PYTHON=python3

# find all python sources (used to determine when to bump build number)
PYTHON_SOURCES:=$(shell find setup.py ${PROJECT} tests -name '*.py')
OTHER_SOURCES:=Makefile Dockerfile setup.py setup.cfg tox.ini README.md LICENSE .gitignore .style.yapf
SOURCES:=${PYTHON_SOURCES} ${OTHER_SOURCES}

# if VERSION=major or VERSION=minor specified, be sure a version bump will happen
$(if ${VERSION},$(shell touch ${PROJECT}/version.py))

help: 
	@echo "make tools|install|uninstall|test|dist|publish|release|clean"

# install python modules for development and testing
tools: 
	${PYTHON} -m pip install --upgrade setuptools pybump pytest tox twine wheel yapf

#TPARM:=-vvx
#test:
#	@echo Testing...
#	pytest $(TPARM)

install:
	@echo Installing ${PROJECT} locally
	${PYTHON} -m pip install --upgrade --editable .

uninstall: 
	@echo Uninstalling ${PROJECT} locally
	${PYTHON} -m pip uninstall -y ${PROJECT} 

# ensure no uncommitted changes exist
gitclean: 
	$(if $(shell git status --porcelain), $(error "git status dirty, commit and push first"))

# yapf format all changed python sources
fmt: .fmt  
.fmt: ${PYTHON_SOURCES}
	@$(foreach s,$?,yapf -i -vv ${s};) 
	@touch $@

# bump version in VERSION and in python source if source files have changed since last version bump
version: VERSION
VERSION: ${SOURCES}
	@echo Changed files: $?
	# If VERSION=major|minor or sources have changed, bump corresponding version element
	# and commit after testing for any other uncommitted changes.
	#
	@pybump bump --file VERSION --level $(if ${VERSION},${VERSION},'patch')
	@/bin/echo -e >${PROJECT}/version.py "DATE='$$(date +%Y-%m-%d)'\nTIME='$$(date +%H:%M:%S)'\nVERSION='$$(cat VERSION)'"
	@echo "Version bumped to `cat VERSION`"
	@touch $@

# test with tox if sources have changed
.PHONY: tox
tox: .tox
.tox: ${SOURCES} VERSION
	@echo Changed files: $?
	TOX_TESTENV_PASSENV="TXTRADER_HOST TXTRADER_HTTP_PORT TXTRADER_TCP_PORT TXTRADER_USERNAME TXTRADER_PASSWORD TXTRADER_API_ACCOUNT" tox
	@touch $@

# create distributable files if sources have changed
dist: .dist
.dist:	${SOURCES} .tox
	@echo Changed files: $?
	@echo Building ${PROJECT}
	${PYTHON} setup.py sdist bdist_wheel
	@touch $@

# set a git release tag and push it to github
release: gitclean .dist 
	@echo pushing Release ${PROJECT} v`cat VERSION` to github...
	TAG="v`cat VERSION`"; git tag -a $$TAG -m "Release $$TAG"; git push origin $$TAG

LOCAL_VERSION=$(shell cat VERSION)
PYPI_VERSION=$(shell pip search txtrader|awk '/${PROJECT_NAME}/{print substr($$2,2,length($$2)-2)}')

pypi: release
	$(if $(wildcard ~/.pypirc),,$(error publish failed; ~/.pypirc required))
	@if [ "${LOCAL_VERSION}" != "${PYPI_VERSION}" ]; then \
	  echo publishing ${PROJECT} `cat VERSION` to PyPI...;\
	  ${PYTHON} -m twine upload dist/*;\
	else \
	  echo ${PROJECT} ${LOCAL_VERSION} is up-to-date on PyPI;\
	fi

docker: .docker
.docker: pypi
	@echo building docker image
	docker images | awk '/^${ORG}\/${PROJECT_NAME}/{print $$3}' | xargs -r -n 1 docker rmi -f
	docker build dockerhub --tag ${ORG}/${PROJECT_NAME}:$(shell cat VERSION)
	docker build dockerhub --tag ${ORG}/${PROJECT_NAME}:latest
	@touch $@

dockerhub: .dockerhub
.dockerhub: .docker 
	$(if $(wildcard ~/.docker/config.json),,$(error docker-publish failed; ~/.docker/config.json required))
	@echo pushing images to dockerhub
	docker login
	docker push ${ORG}/${PROJECT_NAME}:$(shell cat VERSION)
	docker push ${ORG}/${PROJECT_NAME}:latest

publish: .dockerhub

# remove all temporary files
clean:
	@echo Cleaning up...
	rm -rf build dist .dist ./*.egg-info .pytest_cache .tox
	find . -type d -name __pycache__ | xargs rm -rf
	find . -name '*.pyc' | xargs rm -f
# txTrader makefile

rebuild: fmt
	echo "REVISION='$$(git log -1 --pretty=oneline)'" >txtrader/revision.py
	docker-compose build --no-cache

build: fmt
	echo "REVISION='$$(git log -1 --pretty=oneline)'" >txtrader/revision.py
	docker-compose build 

# run the service locally
run:
	envdir /etc/txtrader docker-compose run --rm --service-ports txtrader | tee log

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
	docker-compose run --rm --entrypoint /bin/bash txtrader -l -c 'pytest ${TPARM} ${TESTS}'

# start a shell in the container with the dev directory bind-mounted
shell:
	docker-compose run --rm --entrypoint /bin/bash -v $$(pwd)/txtrader:/home/txtrader/txtrader txtrader -l

debug: build
	docker-compose run --rm --service-ports -v $$(pwd)/txtrader:/home/txtrader/txtrader txtrader /bin/bash -l -c "txtraderd --debug"

# tail the log of any running txtrader container
tail:
	@while true; do (docker ps -q --filter name=txtrader_txtrader_1 | xargs -r docker logs --follow); echo -n '.'; sleep 3; done
