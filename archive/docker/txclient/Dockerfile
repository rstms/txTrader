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
RUN cat /tmp/public_key >> /root/.ssh/authorized_keys
RUN mkdir /home/txtrader/.ssh
RUN cat /tmp/public_key >> /home/txtrader/.ssh/authorized_keys 
RUN chown -R txtrader.txtrader /home/txtrader/.ssh
RUN rm -f /tmp/public_key

RUN \
  su -l txtrader -c ' \
  curl --location https://github.com/rstms/IbPy/tarball/master | tar zxfv - && \
  mv rstms-IbPy-* IbPy && \
  cd IbPy && \
  python setup.py sdist'

RUN mkdir /var/svc.d

RUN \
  su -l txtrader -c ' \
  curl --location https://github.com/rstms/txTrader/tarball/master | tar zxfv - && \
  mv rstms-txTrader-* txTrader && \
  cd txTrader && \
  sudo make config && \
  make build && \
  sudo make -e install'

COPY /keys/server_key /root/.ssh/txtrader
COPY /keys/server_host /root/txtrader_host
COPY /keys/server_user /root/txtrader_user

RUN \
   mkdir /var/svc.d/sshrelay &&\
   mkdir /var/svc.d/sshrelay/log &&\
   mkdir /var/log/sshrelay
    
COPY sshrelay.run /var/svc.d/sshrelay/run
COPY log.run /var/svc.d/sshrelay/log/run

RUN \
  chmod +x /var/svc.d/sshrelay/run && \
  chmod +x /var/svc.d/sshrelay/log/run

RUN \
  ssh-keyscan $(cat /root/txtrader_host) >/root/.ssh/known_hosts

RUN update-service --add /var/svc.d/sshrelay
