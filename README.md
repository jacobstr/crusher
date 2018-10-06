# Crusher API Server

The API server that responds to slack webhooks and provides discovery endpoints
utilized by the corresponding [worker](https://github.com/jacobstr/reserver).

# Running on a PI

I was tempted to install this thing on a small k8s cluster in GCP but though
better of it - $10/mo was just another recurring bill on top of Netflix and
Sour candies that I couldn't afford. Instead it's running on a Raspberry PI,
configured like one might have configured their "pets" in the past:

- It's got some upstart jobs in /etc/init.
- It's using virtualenvs.
- It's got a /crush folder with a bunch of jank inside of it.

There's a crontab to pull from git periodically.
