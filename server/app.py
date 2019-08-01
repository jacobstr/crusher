import hashlib
import hmac
import itertools
import json
import logging
import os
import random
import shelve
import textwrap

import arrow
import flask
import humanhash
from slackclient import SlackClient

logging.basicConfig(level=logging.DEBUG)
LOGGER = logging.getLogger(__name__)

app = flask.Flask(__name__)

#: Url format for HTTP api requests to recreation.gov for a given campsite id.
CAMPGROUND_URL = "https://www.recreation.gov/camping/campgrounds/{id}"

#: Maps known general general camping areas to reserve-america-scraper
#: campground names.
CAMPGROUNDS = [
    {
        "short_name": "Upper Pines",
        "name": "UPPER_PINES",
        "id": "232447",
        "tags": ["yosemite-valley", "yosemite"],
        "tz": "US/Pacific",
    },
    {
        "short_name": "Lower Pines",
        "name": "LOWER_PINES",
        "id": "232450",
        "tags": ["yosemite-valley", "yosemite"],
        "tz": "US/Pacific",
    },
    {
        "short_name": "North Pines",
        "name": "NORTH_PINES",
        "id": "232449",
        "tags": ["yosemite-valley", "yosemite"],
        "tz": "US/Pacific",
    },
    {
        "short_name": "Dry Gulch",
        "name": "DRY_GULCH",
        "id": "233842",
        "tags": ["yosemite"],
        "tz": "US/Pacific",
    },
    {
        "short_name": "Tuolumne Meadows",
        "name": "TUOLOUMME",
        "id": "232448",
        "tags": ["yosemite", "tuolumne"],
        "tz": "US/Pacific",
    },
    {
        "short_name": "Crane Flat",
        "name": "CRANE_FLAT",
        "id": "232452",
        "tags": ["yosemite"],
        "tz": "US/Pacific",
    },
    {
        "short_name": "Hodgdon Meadow",
        "name": "HODGDON_MEADOW",
        "id": "232451",
        "tags": ["yosemite"],
        "tz": "US/Pacific",
    },
    {
        "short_name": "Dirt Flat",
        "name": "DIRT_FLAT",
        "id": "233839",
        "tags": ["yosemite"],
        "tz": "US/Pacific",
    },
    {
        "short_name": "Tuolumne Meadows",
        "name": "TOULUMNE_MEADOWS",
        "id": "232448",
        "tags": ["yosemite", "tuolumne"],
        "tz": "US/Pacific",
    },
    {
        "short_name": "Kalaloch",
        "name": "KALALOCH",
        "id": "232464",
        "tags": ["mt-olympic"],
        "tz": "US/Pacific",
    },
    {
        "short_name": "Sol Duc",
        "name": "SOL_DUC",
        "id": "251906",
        "tags": ["mt-olympic"],
        "tz": "US/Pacific",
    },
]
#: Known campground tags formed via a superset of all tags in the CAMPGROUNDS
#: collection defined above. CAMPGROUNDS is the authoriative source for this
#: data.
CAMPGROUND_TAGS = list(set(itertools.chain.from_iterable([cg['tags'] for cg in CAMPGROUNDS])))
#: The API token for the slack bot can be obtained via:
#: https://api.slack.com/apps/AD3G033C4/oauth?
SLACK_API_KEY = os.getenv('SLACK_API_KEY')
#: Shared secret used to sign requests.
SLACK_SIGNING_SECRET = os.getenv('SLACK_SIGNING_SECRET')
#: In addition to @messaging the user that registered the watcher,
#: the bot will also messsage this public channel.
PUBLIC_RESULTS_CHANNEL = "campsites"
#: This should match the name of the application, using a different name
#: is a from of masquerading and may require additional permissions.
BOT_NAME = "CrusherScrape"
#: The path to the watcher database.
REPO_PATH = os.getenv('CRUSHER_REPO_PATH', '/tmp/crusher.db')


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
WATCHERS = WatchersRepo(REPO_PATH)


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
    if campground not in CAMPGROUND_TAGS:
        return flask.jsonify({
            "response_type": "ephemeral",
            "text": "Unknown camping area, please select one of {}".format(
                ', '.join(CAMPGROUND_TAGS),
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


@app.route('/meta/campgrounds')
def meta_campgrounds():
    return flask.jsonify(CAMPGROUNDS)


@app.route('/meta/tags')
def meta_campground_tags():
    return flask.jsonify(CAMPGROUND_TAGS)


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

    has_changed = results_changed(old_results, results)
    if len(results) and not watcher.get('silenced') and has_changed:
        slack = SlackClient(SLACK_API_KEY)
        resp = slack.api_call(
            "chat.postMessage",
            username=BOT_NAME,
            text="New campsites available!",
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


def slack_list_campgrounds(tags):
    cgs = []
    for cg in CAMPGROUNDS:
        # Check intersection if tags is non-empty.
        if tags and not set(tags) & set(cg['tags']):
            continue
        cgs.append({
            "fallback": "Campground metadata",
            "mrkdwn_in": ["text"],
            "title": cg['short_name'],
            "title_link": CAMPGROUND_URL.format(id=cg['id']),
            "fields": [
                {
                    "title": "tags",
                    "value": ", ".join(cg['tags']),
                    "short": True,
                },
            ],
        })

    if cgs:
        return flask.jsonify({
            "response_type": "in_channel",
            "text": "Campgrounds",
            "attachments": cgs,
        })
    else:
        return flask.jsonify({
            "response_type": "in_channel",
            "text": "No campgrounds match the given tags.",
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

    /crush watch <campground-tag> <DD/MM/YY> <length>
    ------------------------------------------------------
    Registers a new watcher for a reservation. This will begin a periodic
    scraping process against the recreation.gov website. When succesful we'll
    send you a slack message with results.

    Campgrounds are selected according to `campground-tag` you provide. The bot
    will attempt to find sites within any campground that matches the tag you
    provide.

    To list campgrounds and their tags, use the `campgrounds` command.

    /crush list
    ----------------------
    Lists active watchers for all reservations.

    /crush campgrounds [tags...]
    ------------------
    Lists known campgrounds, optionally filtered by those that match any of the
    provided tags. For example, if you wish to list what the bot considers
    a 'yosemite-valley' campground use `/crush campgrounds yosemite-valley`.

    Syntax:
        - Square brackets, as in `[param]`, denote optional parameters.
        - Angle brackets, as in `<param>`, denote required parameters.
        - Ellipsis, `...` following a parameter denote a space-separated list.

    """
    raw_data = flask.request.get_data()
    if not verify_slack_request(
        flask.request.headers['X-Slack-Signature'],
        flask.request.headers['X-Slack-Request-Timestamp'],
        raw_data,
    ):
        return flask.Response(status_code=400)

    text = flask.request.form['text']
    if len(text) == 0:
        return flask.jsonify({
            "response_type": "ephemeral",
            # We re-use the docstring in this function as the help text.
            "text": "I need a subcommand!\n```{}```".format(textwrap.dedent(slack_slash_commands.__doc__))
        })

    # Request payload mangling and subcommand delegation occurs.
    parts = text.split(' ')
    command = parts[0]
    args = parts[1:]
    if command == 'watch':
        if len(args) != 3:
            return flask.jsonify({
                "response_type": "ephemeral",
                "text": "Please use a format like `tuolumne DD/MM/YY <length>`."
            })
        campground, start, length = args

        try:
            date = arrow.get(start, 'DD/MM/YY')
        except:
            return flask.jsonify({
                "response_type": "ephemeral",
                "text": "Could not parse your date, please use a DD/MM/YY format.",
            })
        # Hackish workaround: 01/01/2019 successfully parses via DD/MM/YY above,
        # but will subsequently get interpretted as e.g. "2020" - ignoring the
        # latter two characters.
        if date.format('DD/MM/YY') != start:
            return flask.jsonify({
                "response_type": "ephemeral",
                "text": "Could not parse your date, please use a DD/MM/YY format.",
            })
        user_id = flask.request.form['user_id']
        return add_watcher(user_id, campground, start, int(length))
    elif command == 'list':
        return slack_list_watchers()
    elif command == 'campgrounds':
        return slack_list_campgrounds(args)
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
        "title": "Found a {} on {} at {} site {} for {:.0%} of requested stay.".format(
            ':unicorn_face:' if result['fraction'] == 1 else 'site',
            result['date'],
            result['campground']['short_name'],
            result['campsite']['site'],
            result['fraction'],
        ),
        "title_link": result['url'],
    } for result in results]


# Thanks Jani Karhunen: https://janikarhunen.fi/verify-slack-requests-in-aws-lambda-and-python.html
def verify_slack_request(slack_signature=None, slack_request_timestamp=None, request_body=None):
    ''' Form the basestring as stated in the Slack API docs. We need to make a bytestring. '''
    basestring = "v0:{slack_request_timestamp}:{request_body}".format(
        slack_request_timestamp=slack_request_timestamp,
        request_body=request_body,
    )

    ''' Create a new HMAC "signature", and return the string presentation. '''
    my_signature = 'v0=' + hmac.new(SLACK_SIGNING_SECRET, basestring, hashlib.sha256).hexdigest()

    ''' Compare the the Slack provided signature to ours.
    If they are equal, the request should be verified successfully.
    Log the unsuccessful requests for further analysis
    (along with another relevant info about the request). '''
    if hmac.compare_digest(str(my_signature), str(slack_signature)):
        return True
    else:
        LOGGER.warning("Verification failed. my_signature: {my_signature}")
        return False
