FROM python:3.8.3-buster

MAINTAINER mkrueger@rstms.net

RUN python -m pip install --upgrade pip && \
  pip install \
  click==7.1.2 \
  hexdump==3.3 \
  pytz==2020.1 \
  twisted==20.3.0 \
  tzlocal==2.1 \
  txtrader-client==1.5.4 \
  txtrader-monitor==1.1.7 \
  ujson==3.1.0 \
  pytest==6.0.1 \
  requests==2.24.0 \
  pybump==1.2.5 \
  tox==3.19.0 \
  twine==3.2.0 \
  wait-for-it==2.1.0 \
  wheel==0.34.2 \
  yapf==0.30.0

RUN \
  apt-get update && \  
  apt-get install -yq --no-install-recommends \
  less \
  vim && \
  apt-get clean && rm -rf /var/lib/apt/lists/*

RUN \
  echo 'America/Chicago' >/etc/timezone \
  && rm /etc/localtime \
  && dpkg-reconfigure -f noninteractive tzdata

RUN useradd -m txtrader
#USER txtrader
WORKDIR /home/txtrader
COPY txtrader /home/txtrader/txtrader
COPY setup.py /home/txtrader
COPY README.md /home/txtrader
COPY pytest.ini /home/txtrader
COPY tests /home/txtrader/tests
RUN mkdir -p /home/txtrader/.local/bin
RUN pip install . --user --no-warn-script-location

COPY entrypoint.sh /home/txtrader
COPY txtrader/txtrader.tac /home/txtrader
ENTRYPOINT ["/bin/sh", "entrypoint.sh"]
