#!/usr/bin/env python

import json
import logging
import os
import random
import time
from pathlib import Path

import arrow
import requests
import schedule
from slackclient import SlackClient

logging.basicConfig(level=logging.DEBUG)
LOGGER = logging.getLogger(__name__)

#: Url format for HTTP api requests to recreation.gov for a given campsite id.
CAMPGROUND_URL = "https://www.recreation.gov/camping/campgrounds/{id}"
CRUSHER_HOST = os.getenv('CRUSHER_HOST', 'http://localhost:5000')
CRUSHER_RESULTS_URL = os.getenv('CRUSHER_RESULTS_URL', '{}/watchers/{{id}}/results'.format(CRUSHER_HOST))
CRUSHER_CAMPGROUNDS_URL = os.getenv('CRUSHER_CAMPGROUNDS_URL', '{}/meta/campgrounds'.format(CRUSHER_HOST))
CRUSHER_WATCHER_LISTING_URL = os.getenv('CRUSHER_WATCHER_LISTING_URL', '{}/watchers'.format(CRUSHER_HOST))
CRUSHER_POLLING_INTERVAL_MINUTES = int(os.getenv('CRUSHER_POLLING_INTERVAL_MINUTES', '3'))
HEARTBEAT_FILENAME = os.getenv('CRUSHER_HEARTBEAT_FILENAME', '/tmp/worker-health')
#: The API token for the slack bot can be obtained via:
#: https://api.slack.com/apps/AD3G033C4/oauth?
SLACK_API_KEY = os.getenv('SLACK_API_KEY')


def campgrounds():
    try:
        resp = requests.get(CRUSHER_CAMPGROUNDS_URL)
        resp.raise_for_status()
        return resp.json()
    except:
        LOGGER.exception("failed to get campgrounds - proceeding with empty campgrounds.")
        return []


def campgrounds_by_tag(tag):
    results = []
    for cg in campgrounds():
        if tag in cg['tags']:
            results.append(cg)
    return results


def send_watcher_results(watcher_id, results):
    """
    :param watcher_id: The job id used to correlate with a watch task on the web server.
    :param results: A list of dicts with a fairly ad-hoc structure.
    """
    LOGGER.debug("got results %s", results)
    resp = requests.post(
        CRUSHER_RESULTS_URL.format(**{'id': watcher_id}),
        json=results,
    )
    if resp.status_code != 200:
        LOGGER.debug("unexpected status posting results: %d", resp.status_code)


def get_watchers():
    """
    Obtains the list of watcher tasks from the API server.
    """
    resp = requests.get(CRUSHER_WATCHER_LISTING_URL)
    if resp.status_code != 200:
        LOGGER.error("failed to list watchers")
    return resp.json()


def availability_fraction(site, start_date, end_date):
    interested_dates = []
    total_days = (end_date - start_date).days
    total_matched = 0.0
    for avdate, status in list(site['availabilities'].items()):
        avparsed = arrow.get(avdate)
        # Ignore dates outside of our interested range.
        if not (avparsed >= start_date and avparsed < end_date):
            continue
        if status.lower() == 'available':
            total_matched = total_matched + 1
    return total_matched / total_days


def run(watcher, date, length, campground):
    start_date = arrow.get(date, 'DD/MM/YY')
    end_date = start_date.shift(days=length)

    # A sample site payload:
    # {
    #     "availabilities": {
    #         "2018-10-05T00:00:00Z": "Reserved",
    #         ...
    #         "2018-10-20T00:00:00Z": "reserved"
    #     },
    #     "campsite_id": "99",
    #     "campsite_reserve_type": "Site-Specific",
    #     "loop": "UPPER PINES ",
    #     "quantities": null,
    #     "site": "043"
    # }
    resp = requests.get(
        'https://www.recreation.gov/api/camps/availability/campground/{id}/month'.format(id=campground['id']),
        headers={'User-Agent': 'Mozilla/5.0 (Macintosh; Intel Mac OS X 10_14_2) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/73.0.3683.75 Safari/537.36'},
        params={
            'start_date': start_date.format('YYYY-MM-01T00:00:00.000') + 'Z',
        }
    )

    if resp.status_code != 200:
        LOGGER.error("request failed: %s, %s", watcher.get('user_id'), resp.headers, resp.content)
        try:
            slack = SlackClient(SLACK_API_KEY)
            resp = slack.api_call(
                "chat.postMessage",
                channel="#campsites",
                text="Campsite search failed for %s: <STATUS %s>: %s" % (watcher.get('user_id'), resp.text,resp.status_code),
            )
        except:
            LOGGER.exception('failed to notify slack of error')
        return []

    LOGGER.debug("response from recreation.gov: %s", json.dumps(resp.json()))

    responses = [resp.json()]
    # The api requires getting availabilities by month at a time. If we're
    # looking for a reservation that spans multiple months, we need to look at
    # multiple months worth of availabilities. We assume that no one is staying
    # longer than one month and will make at most 2 requests.
    if start_date.month != end_date.month:
        resp = requests.get(
            'https://www.recreation.gov/api/camps/availability/campground/{id}/month'.format(id=campground['id']),
            headers={'User-Agent': 'Mozilla/5.0 (Macintosh; Intel Mac OS X 10_14_2) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/73.0.3683.75 Safari/537.36'},
            params={
                'start_date': end_date.format('YYYY-MM-01T00:00:00.000') + 'Z',
            }
        )

        if resp.status_code != 200:
            LOGGER.error("request failed: %s, %s", resp.headers, resp.content)
            return []

        responses.append(resp.json())

    def _collect_sites(responses):
        """
        Helps mangle multiple responses into a single index of availbilities by
        site id.
        """
        availabilities_by_site = {}
        for payload in responses:
            for site_id, site in payload['campsites'].items():
                if not availabilities_by_site.get(site_id):
                    availabilities_by_site[site_id] = {
                        'site': site,
                        'availabilities': {},
                    }
                availabilities_by_site[site_id]['availabilities'].update(site['availabilities'])
        return availabilities_by_site

    results = []
    for site_id, site in _collect_sites(responses).items():
        avfraction = availability_fraction(site, start_date, end_date)
        if avfraction > 0:
            results.append({
                "date": date,
                "url": "https://www.recreation.gov/camping/campgrounds/{}/availability".format(campground['id']),
                "campground": campground,
                "campsite": site['site'],
                "fraction": avfraction,
            })

    # Return the list of sites by their availability fraction of the dates
    # desired since we prefer not to move campsites, but will if we have to.
    return sorted(results, key=lambda site: site['fraction'], reverse=True)


def mock_watchers():
    return [
        {
            "id": "woot",
            "start": "26/10/18",
            "length": 3,
            "campground": "yosemite",
        }
    ]


def run_all():
    watchers = get_watchers()
    LOGGER.info("running watcher loop with %d watchers", len(watchers))
    for watcher in watchers:
        date = watcher['start']
        length_of_stay = watcher['length']
        campgrounds = campgrounds_by_tag(watcher['campground'])
        watcher_id = watcher['id']
        LOGGER.info("looking for camspites in %s", campgrounds)

        results = []
        for cg in campgrounds:
            results.extend(run(
                watcher,
                date,
                length_of_stay,
                cg,
            ))
        send_watcher_results(watcher_id, results)
    LOGGER.info("writing heartbeat to %s", HEARTBEAT_FILENAME)
    Path(HEARTBEAT_FILENAME).touch()


if __name__ == '__main__':
    LOGGER.info("Started...")
    schedule.every(CRUSHER_POLLING_INTERVAL_MINUTES).minutes.do(run_all)
    # Run our scraper on the "rising edge", generally for the sake of
    # debuggability since we want to invoke the scraper immediately when running
    # from the command line.
    run_all()
    while True:
        schedule.run_pending()
        time.sleep(1)
