#!/bin/bash

# Update crusher code.
cd /crush/crusher
if [[ $(git rev-list HEAD...origin/master --count) -ne "0" ]]; then
    git fetch && git reset --hard origin/master
    cp -f contrib/upstart/crusher.conf /etc/init/crusher.conf
    cp -f contrib/upstart/crusher.conf /etc/init/ngrok.conf
    sudo service crusher restart
fi

# Update reserver code.
cd /crush/reserver
if [[ $(git rev-list HEAD...origin/master --count) -ne "0" ]]; then
    git fetch && git reset --hard origin/master
    cp -f contrib/upstart/reserver.conf /etc/init/reserver.conf
    sudo service reserver restart
fi
