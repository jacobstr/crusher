import hashlib
import json
import os
import random
import shelve
import textwrap

import arrow
import flask
import humanhash
from slackclient import SlackClient

app = flask.Flask(__name__)

#: Maps known general general camping areas to reserve-america-scraper
#: campground names.
KNOWN_CAMPGROUNDS = {
    'yosemite': ['UPPER_PINES', 'LOWER_PINES', 'NORTH_PINES'],
    'tuolumne': ['TUOLUMNE'],
    'easy': ['ANTHONY_CHABOT'],
}

#: The API token for the slack bot can be obtained via:
#: https://api.slack.com/apps/AD3G033C4/oauth?
SLACK_API_KEY = os.getenv('SLACK_API_KEY')
#: In addition to @messaging the user that registered the watcher,
#: the bot will also messsage this public channel.
PUBLIC_RESULTS_CHANNEL = "campsites"
#: This should match the name of the application, using a different name
#: is a from of masquerading and may require additional permissions.
BOT_NAME = "CrusherScrape"


class WatchersRepo(object):
    """
    Ghetto jank interface around our mega-lame disk-based database. We store
    reservations as list instead of a dict because the assumption is this thing
    will not get very large - in fact we'll probably enforce it - and it
    seemed appropriate that contents should be ordered.
    """
    KEY = 'watchers'

    def __init__(self, path):
        self.path = path

    def _set(self, data):
        s = shelve.open(self.path, writeback=True)
        try:
            s[self.KEY] = data
        finally:
            s.close()

    def list(self):
        s = shelve.open(self.path)
        try:
            watchers = s[self.KEY]
        except KeyError:
            return []
        finally:
            s.close()
        return watchers

    def remove(self, watcher_id):
        watchers = filter(lambda x: x['id'] != watcher_id, self.list())
        self._set(watchers)
        return watchers

    def get(self, watcher_id):
        watchers = filter(lambda x: x['id'] == watcher_id, self.list())
        if len(watchers) > 0:
            return watchers[0]
        else:
            return None

    def update(self, watcher):
        watchers = self.list()
        for i, w in enumerate(watchers):
            if w['id'] == watcher['id']:
                watchers[i] = watcher
                break
        self._set(watchers)

    def append(self, watcher):
        watchers = self.list()
        watchers.append(watcher)
        self._set(watchers)


#: Global disk-based database of watcher registrations.
WATCHERS = WatchersRepo('/tmp/crusher.db')


def random_id():
    return humanhash.humanize(hashlib.md5(os.urandom(32)).hexdigest())


def make_watcher(user_id, campground, start, length):
    return {
        "id": random_id(),
        "user_id": user_id,
        "campground": campground,
        "start": start,
        "length": length,
        "silenced": False,
    }


def add_watcher(user_id, campground, start, length):
    if campground not in KNOWN_CAMPGROUNDS.keys():
        return flask.jsonify({
            "response_type": "ephemeral",
            "text": "Unknown camping area, please select one of {}".format(
                ', '.join(KNOWN_CAMPGROUNDS.keys()),
            )
        })

    WATCHERS.append(make_watcher(
        user_id,
        campground,
        start,
        length,
    ))

    return flask.jsonify({
        "text": "Thanks <@{}>, I've registered your reservation request for *{}*.".format(
            user_id,
            campground,
        )
    })


@app.route('/watchers')
def watchers_list():
    return flask.jsonify(WATCHERS.list())


@app.route('/watchers/<watcher_id>')
def watchers_get(watcher_id):
    return flask.jsonify(WATCHERS.get(watcher_id))


@app.route('/watchers/<watcher_id>/delete', methods=['POST'])
def watchers_delete(watcher_id):
    return flask.jsonify(WATCHERS.remove(watcher_id))


def results_changed(old, new):
    # Hackish way to compare two lists.
    return json.dumps(old) != json.dumps(new)


@app.route('/watchers/<watcher_id>/results', methods=['POST'])
def watchers_results(watcher_id):
    watcher = WATCHERS.get(watcher_id)
    old_results = watcher.get('results', [])

    #: Trusting random input from the internet here.
    results = flask.request.get_json()
    watcher['results'] = results
    WATCHERS.update(watcher)

    if len(results) and not watcher.get('silenced') and results_changed(old_results, results):
        slack = SlackClient(SLACK_API_KEY)
        resp = slack.api_call(
            "chat.postMessage",
            username=BOT_NAME,
            text="Got some results!",
            channel=watcher['user_id'],
            attachments=make_results_attachments(results),
        )
    return flask.jsonify(watcher)


def slack_list_watchers():
    watchers = WATCHERS.list()
    if len(watchers):
        return flask.jsonify({
            "response_type": "in_channel",
            "attachments": make_watcher_attachments(watchers),
        })
    else:
        return flask.jsonify({
            "response_type": "in_channel",
            "text": "No active watchers at the moment!",
        })


@app.route('/slack/actions', methods=['POST'])
def slack_actions():
    payload = json.loads(flask.request.values['payload'])
    if payload['callback_id'] != 'watcher_manage':
        return flask.jsonify({"text":"Sorry, I didn't get that!"})

    action = payload['actions'][0]
    # Sample payload: see contrib/sample_action_payload.json
    if action['name'] == 'cancel':
        WATCHERS.remove(action['value'])
        return slack_list_watchers()
    if action['name'] == 'results':
        watcher = WATCHERS.get(action['value'])
        return flask.jsonify({
            "text": "Results for {} on {}".format(watcher['campground'], watcher['start']),
            "attachments": make_results_attachments(watcher['results']),
        })
    if action['name'] == 'silence':
        watcher = WATCHERS.get(action['value'])
        watcher['silenced'] = True
        WATCHERS.update(watcher)
        return flask.jsonify({
            "text": "Silenced watcher, will no longer message <@{}>!".format(watcher['user_id']),
        })
    if action['name'] == 'unsilence':
        watcher = WATCHERS.get(action['value'])
        watcher['silenced'] = False
        WATCHERS.update(watcher)
        return flask.jsonify({
            "text": "Unsilenced watcher, will now message <@{}> with results!".format(watcher['user_id']),
        })
    else:
        return flask.jsonify({"text":"Sorry, I didn't get that!"})


@app.route('/slack/commands', methods=['POST'])
def slack_slash_commands():
    """
    Handles responding to slash commands for reservations.

    Commands:

    /crush watch <tuolumne|yosemite> <date> <length>
    ------------------------------------------------------
    Registers a new watcher for a reservation. This will begin a periodic
    scraping process against the reserve america website. When succesful we'll
    send you a slack message with results.

    /crush list
    ----------------------
    Lists active watchers for all reservations.
    """
    text = flask.request.form['text']
    if len(text) == 0:
        return flask.jsonify({
            "response_type": "ephemeral",
            # We re-use the docstring in this function as the help text.
            "text": "I need a subcommand!\n```{}```".format(textwrap.dedent(slack_slash_commands.__doc__))
        })

    # Request payload mangling and subcommand delegation occurs.
    command = text.split(' ', 1)[0]
    if command == 'watch':
        args = text.split(' ')
        if len(args) != 4:
            return flask.jsonify({
                "response_type": "ephemeral",
                "text": "Please use a format like `tuolumne 09/28/18 3`."
            })
        _, campground, start, length = args

        try:
            date = arrow.get(start, 'DD/MM/YY')
        except:
            return flask.jsonify({
                "response_type": "ephemeral",
                "text": "Could not parse your date, please use a DD/MM/YY format.",
            })

        user_id = flask.request.form['user_id']
        return add_watcher(user_id, campground, start, length)
    elif command == 'list':
        return slack_list_watchers()
    elif command == 'help':
        return flask.jsonify({
            "response_type": "ephemeral",
            "text": "```{}```".format(textwrap.dedent(slack_slash_commands.__doc__))
        })
    else:
        return flask.jsonify({
            "response_type": "ephemeral",
            "text": "I haven't been implemented yet!",
        })


def make_watcher_attachments(watchers):
    """
    Returns a json-encodable representation of attachments representing active watchers.
    """
    results = []
    for watcher in watchers:
        watch_results = watcher.get('results')
        if watch_results:
            text = "<@{}> found sites in *{}* from {} for {} day(s).".format(
                watcher['user_id'],
                watcher['campground'],
                watcher['start'],
                watcher['length'],
            )
            color = "#36a64f"
        else:
            text = "<@{}> is looking in *{}* from {} for {} day(s).".format(
                watcher['user_id'],
                watcher['campground'],
                watcher['start'],
                watcher['length'],
            )
            color = "#ccbd22"

        attachment = {
            "fallback": "Required plain-text summary of the attachment.",
            "color": color,
            "text": text,
            "mrkdwn_in": ["text", "pretext"],
            "callback_id": "watcher_manage",
            "actions": [
                {
                    "name": "cancel",
                    "text": "Remove",
                    "style": "danger",
                    "type": "button",
                    "value": watcher['id'],
                    "confirm": {
                        "title": "Are you sure?",
                        "text": "This will cancel scraping for this reservation.",
                        "ok_text": "Yes",
                        "dismiss_text": "No"
                    },
                },
            ]
        }

        if watcher.get('silenced'):
            attachment['actions'].insert(0, {
                "name": "unsilence",
                "text": "Unsilence",
                "type": "button",
                "value": watcher['id'],
            })
        else:
            attachment['actions'].insert(0, {
                "name": "silence",
                "text": "Silence",
                "type": "button",
                "value": watcher['id'],
            })

        if watch_results:
            attachment['actions'].insert(0, {
                "name": "results",
                "text": "Show Results",
                "type": "button",
                "style": "primary",
                "value": watcher['id'],
            })

        results.append(attachment)

    return results


def make_results_attachments(results):
    """
    Returns a json-encodable representation of attachments representing found campsites.
    """
    return [{
        "fallback": "Campsite result.",
        "color": "#36a64f",
        "mrkdwn_in": ["text"],
        "title": "Found a site on {} for {}.".format(
            result['date'],
            result['campground'],
        ),
        "title_link": result['url'],
    } for result in results]
