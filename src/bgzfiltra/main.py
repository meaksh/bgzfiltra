#!/usr/bin/env python3

__author__ = "Jochen Breuer"
__email__ = "jbreuer@suse.de"
__license__ = "MIT"

import os
import sys
import time
import signal
import pickle
import typing
import bugzilla

from bgznet import get_bugs_for_product
from bugzilla.bug import Bug
from datetime import datetime
from persistence import QuestDB
from toml_config import get_settings


def group_bugs_by_assignee(
    bugs: typing.List[Bug],
) -> typing.Dict[str, typing.List[Bug]]:
    """
    Groups list of bugzilla bugs by assignee: Dict[email, (Bug, …)]
    """
    grouped_bugs: typing.Dict[str, typing.List[Bug]] = {}
    for bug in bugs:
        if bug.assigned_to not in grouped_bugs:
            grouped_bugs[bug.assigned_to] = []
        grouped_bugs[bug.assigned_to].append(bug)
    return grouped_bugs


def group_bugs_by_component(
    bugs: typing.List[Bug],
) -> typing.Dict[str, typing.List[Bug]]:
    """
    Groups list of bugzilla bugs by component: Dict[component, (Bug, …)]
    """
    grouped_bugs: typing.Dict[str, typing.List[Bug]] = {}
    for bug in bugs:
        if bug.component not in grouped_bugs:
            grouped_bugs[bug.component] = []
        grouped_bugs[bug.component].append(bug)
    return grouped_bugs


def group_bugs_by_status(
    bugs: typing.List[Bug],
) -> typing.Dict[str, typing.List[Bug]]:
    """
    Groups list of bugzilla bugs by status: Dict[status, (Bug, …)]
    """
    grouped_bugs: typing.Dict[str, typing.List[Bug]] = {}
    for bug in bugs:
        if bug.status not in grouped_bugs:
            grouped_bugs[bug.status] = []
        grouped_bugs[bug.status].append(bug)
    return grouped_bugs


def is_l3(bug: Bug) -> bool:
    """
    Checks if this bug is or was an l3.
    """
    return "wasL3:" in bug.whiteboard or "openL3:" in bug.whiteboard


def has_needinfo(bug: Bug) -> bool:
    """
    Checks if the needinfor flag is set.
    """
    return any(flag.get("name", "") == "needinfo" for flag in bug.flags)


def main(options):
    settings = get_settings()
    db_settings = settings["questdb"]
    products = settings["bugzilla"]["products"]
    timestamp: datetime = datetime.now()

    db = QuestDB()
    db.connect(db_settings)
    db.setup_tables()

    while True:
        for product in products:
            print("Product: {}".format(product))
            bugzilla_bugs = get_bugs_for_product(
                product, settings["bugzilla"], use_cache=options.get("--use-cache", False)
            )
            print("Found %d bugs with our query" % len(bugzilla_bugs))
            bugzilla_l3s = [bug for bug in bugzilla_bugs if is_l3(bug)]

            # Bugs by status
            grouped_bugs = group_bugs_by_status(bugzilla_bugs)
            for status, bugs in grouped_bugs.items():
                db.insert_status(product, status, len(bugs), timestamp)

            # Bugs by component
            grouped_bugs = group_bugs_by_component(bugzilla_bugs)
            for component, bugs in grouped_bugs.items():
                db.insert_component(product, component, len(bugs), timestamp)

            # L3 bugs
            l3s = group_bugs_by_status(bugzilla_l3s)
            for status, bugs in l3s.items():
                db.insert_l3(product, status, len(bugs), timestamp)

            # L3 cases
            results = {"open": 0, "closed": 0}
            for l3 in bugzilla_l3s:
                results["open"] += l3.whiteboard.count("openL3:")
                results["closed"] += l3.whiteboard.count("wasL3:")
            db.insert_l3_cases(product, "open", results["open"], timestamp)
            db.insert_l3_cases(product, "closed", results["closed"], timestamp)

            # Bugs per priority
            results = {"p1": 0, "p2": 0, "p3": 0}
            for bug in bugzilla_bugs:
                prio = bug.priority[:2].lower()
                if prio in results:
                    results[prio] += 1
            for prio, count in results.items():
                db.insert_priority(product, prio, count, timestamp)

            # Open bugs per assignee
            open_bugs = [bug for bug in bugzilla_bugs if bug.status != "RESOLVED"]
            grouped_bugs = group_bugs_by_assignee(open_bugs)
            for email, bugs in grouped_bugs.items():
                db.insert_assigned(product, email, len(bugs), timestamp)

        # default for the interval is 24h
        interval_minutes = int(options.get("<minutes>", 1440))
        print("Waiting for {} minutes.".format(interval_minutes))
        time.sleep(60 * interval_minutes)


def sigint_handler(signal, frame):
    sys.exit(0)


signal.signal(signal.SIGINT, sigint_handler)
