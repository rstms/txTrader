#
# Interactive Brokers TWS & ib-controller
# 
# docker container with VNC Xserver
#
# Adapted from a subset of:
#       https://github.com/QuantConnect/Lean/blob/master/DockerfileLeanFoundation
#	LEAN Foundation Docker Container March-2017
#	Cross platform deployment for multiple brokerages	
#	Intended to be used in conjunction with DockerfileLeanAlgorithm. This is just the foundation common OS+Dependencies required.

# Use base system for cleaning up wayward processes
FROM phusion/baseimage:0.9.19

MAINTAINER mkrueger@rstms.net

EXPOSE 22
EXPOSE 50070
EXPOSE 50090

# Use baseimage-docker's init system.
CMD ["/sbin/my_init"]

# Install OS Packages:
# Misc tools for running Python.NET and IB inside a headless container.
RUN \
  apt-get update

RUN \
  apt-get install -y wget net-tools netcat unzip curl openssh-server git daemontools ucspi-tcp sudo

RUN \
  apt-get install -y python-pip

RUN \
  pip install --upgrade pip

RUN \
  pip install virtualenv twisted redis

RUN \
echo 'America/New_York' >/etc/timezone && \
rm /etc/localtime && \
dpkg-reconfigure -f noninteractive tzdata

# add user account and configure
RUN useradd -m txtrader -Gsudo
RUN sed -e "s|^%sudo.*$|%sudo ALL=(ALL:ALL) NOPASSWD:ALL|" -i /etc/sudoers
RUN rm /etc/service/sshd/down
COPY keys/public_key /tmp/public_key
RUN cat /tmp/public_key >> /root/.ssh/authorized_keys && rm -f /tmp/public_key

RUN \
  su -l txtrader -c ' \
  curl --location https://github.com/rstms/IbPy/tarball/master | tar zxfv - && \
  mv rstms-IbPy-* IbPy && \
  cd IbPy && \
  python setup.py sdist \
  '

RUN mkdir /var/svc.d

RUN \
  su -l txtrader -c ' \
  curl --location https://github.com/rstms/txTrader/tarball/master | tar zxfv - && \
  mv rstms-txTrader-* txTrader && \
  cd txTrader && \
  echo ibgw >etc/txtrader/TXTRADER_API_HOST && \
  echo 4001 >etc/txtrader/TXTRADER_API_PORT && \
  sudo make config && \
  make build && \
  sudo make -e install && \
  sudo make start \
  '

COPY keys/github-rsstools-deploy /root/.ssh/github-rsstools-deploy
RUN \
  echo "Host rsstools" >/root/.ssh/config && \
  echo "Hostname github.com" >>/root/.ssh/config && \
  echo "IdentityFile /root/.ssh/github-rsstools-deploy" >>/root/.ssh/config

RUN \
  ln -s /etc/service /service && \
  ssh-keyscan -t rsa github.com >> /root/.ssh/known_hosts && \
  git clone git@rsstools:rstms/rsstools.git && \
  cd rsstools && \
  pip install . && \
  rm -rf /var/svc.d/rssapipub && \
  cp -rp service/rssapipub /var/svc.d && \
  chown -R root.root /var/svc.d/rssapipub && \
  chown root.txtrader /var/svc.d/rssapipub && \
  ip route | awk '/^default/{print $3}' >/var/svc.d/rssapipub/env/RSS_REDIS_HOST && \
  cp /etc/txtrader/TXTRADER_USERNAME /var/svc.d/rssapipub/env/RSS_XMLRPC_USERNAME && \
  cp /etc/txtrader/TXTRADER_PASSWORD /var/svc.d/rssapipub/env/RSS_XMLRPC_PASSWORD && \
  mkdir /var/log/rssapipub && \
  update-service --add /var/svc.d/rssapipub

