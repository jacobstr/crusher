#!/bin/bash

# Update crusher code.
cd /crush/crusher
if [[ $(sudo -u crusher git fetch && sudo git rev-list HEAD...origin/master --count) -ne "0" ]]; then
    sudo -u crusher git fetch && sudo -u crusher git reset --hard origin/master
    sudo cp -f contrib/upstart/crusher.conf /etc/init/crusher.conf
    sudo cp -f contrib/upstart/ngrok.conf /etc/init/ngrok.conf
    sudo service crusher restart
    sudo chown -R crusher:crusher /crush
fi

# Update reserver code.
cd /crush/reserver
if [[ $(sudo -u crusher git fetch && sudo -u crusher git rev-list HEAD...origin/master --count) -ne "0" ]]; then
    sudo -u crusher git fetch && sudo -u crusher git reset --hard origin/master
    sudo cp -f contrib/upstart/reserver.conf /etc/init/reserver.conf
    sudo service reserver restart
    sudo chown -R crusher:crusher /crush
fi
