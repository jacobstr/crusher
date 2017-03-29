#!/usr/bin/env python

from __future__ import print_function

import logging
import os
import random
import time

import arrow
import requests
import schedule

logging.basicConfig(level=logging.DEBUG)
LOGGER = logging.getLogger(__name__)

#: Url format for HTTP api requests to recreation.gov for a given campsite id.
CAMPGROUND_URL = "https://www.recreation.gov/camping/campgrounds/{id}"

#: Somewhat customized crusherbot metadata.
CAMPGROUNDS = [
    {
        "short_name": "Upper Pines",
        "name": "UPPER_PINES",
        "id": "232447",
        "tags": ["yosemite-valley", "yosemite"],
    },
    {
        "short_name": "Lower Pines",
        "name": "LOWER_PINES",
        "id": "232450",
        "tags": ["yosemite-valley", "yosemite"],
    }
]

CRUSHER_RESULTS_URL = os.getenv('CRUSHER_RESULTS_URL', 'http://localhost:5000/watchers/{id}/results')
CRUSHER_WATCHER_LISTING_URL = os.getenv('CRUSHER_WATCHER_LISTING_URL', 'http://localhost:5000/watchers')
CRUSHER_POLLING_INTERVAL_MINUTES = int(os.getenv('CRUSHER_POLLING_INTERVAL_MINUTES', '3'))

def campgrounds_by_tag(tag):
    results = []
    for cg in CAMPGROUNDS:
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


def run(watcher_id, date, length, campground):
    start_date = arrow.get(date, 'DD/MM/YY')
    end_date = start_date.shift(days=length)

    resp = requests.get(
        'https://www.recreation.gov/api/camps/availability/campground/{id}'.format(id=campground['id']),
        params={
            'start_date': start_date.format('YYYY-MM-DDTHH:mm:ssZZ'),
            'end_date': end_date.format('YYYY-MM-DDTHH:mm:ssZZ'),
        }
    )

    if resp.status_code != 200:
        return []

    results = []
    for site_id, site in resp.json()['campsites'].iteritems():
        for avdate, status in list(site['availabilities'].iteritems())[:length]:
            if status.lower() == 'available':
                results.append({
                    "date": date,
                    "url": "https://www.recreation.gov/camping/campgrounds/{}/availability".format(campground['id']),
                    "campground": campground,
                })

    return results


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
                watcher_id,
                date,
                length_of_stay,
                cg,
            ))
        send_watcher_results(watcher_id, results)


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
