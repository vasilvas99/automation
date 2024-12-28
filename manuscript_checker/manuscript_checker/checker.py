import logging
from enum import Enum
from os import environ
from typing import List

import brevo_python
import requests
from dotenv import load_dotenv
from pydantic import BaseModel, Field
from pymongo.mongo_client import MongoClient
from pymongo.server_api import ServerApi

load_dotenv()


def init_log():
    logging.basicConfig(level=logging.INFO)
    logger = logging.getLogger("MANUSCRIPT_CHECKER")
    return logger


logger = init_log()
API_BASE = "https://tnlkuelk67.execute-api.us-east-1.amazonaws.com/tracker/{uuid}"


class ReviewerEvent(str, Enum):
    INVITED = "REVIEWER_INVITED"
    ACCEPTED = "REVIEWER_ACCEPTED"
    COMPLETED = "REVIEWER_COMPLETED"


class ReviewEvent(BaseModel):
    date: int = Field(alias="Date")
    event: ReviewerEvent = Field(alias="Event")
    revision: int = Field(alias="Revision")
    id: int = Field(alias="Id")


class ManuscriptReviewStatus(BaseModel):
    uuid: str = Field(alias="Uuid")
    corresponding_author: str = Field(alias="CorrespondingAuthor")
    document_id: int = Field(alias="DocumentId")
    first_author: str = Field(alias="FirstAuthor")
    journal_acronym: str = Field(alias="JournalAcronym")
    journal_name: str = Field(alias="JournalName")
    last_updated: int = Field(alias="LastUpdated")
    latest_revision_number: int = Field(alias="LatestRevisionNumber")
    manuscript_title: str = Field(alias="ManuscriptTitle")
    pubd_number: str = Field(alias="PubdNumber")
    review_events: List[ReviewEvent] = Field(alias="ReviewEvents")
    status: int = Field(alias="Status")
    submission_date: int = Field(alias="SubmissionDate")


class EmailNotifier:
    def __init__(self, brevo_api_key, sender, to):
        configuration = brevo_python.Configuration()
        configuration.api_key["api-key"] = brevo_api_key
        self.brevo = brevo_python.TransactionalEmailsApi(
            brevo_python.ApiClient(configuration)
        )
        self.to = to
        self.sender = sender

    def aggregate_status(self, status: ManuscriptReviewStatus):
        invited = 0
        accepted = 0
        completed = 0
        for e in status.review_events:
            if e.event == ReviewerEvent.COMPLETED:
                completed += 1
            elif e.event == ReviewerEvent.INVITED:
                invited += 1
            elif e.event == ReviewerEvent.ACCEPTED:
                accepted += 1
        return invited, accepted, completed

    def __call__(self, status: ManuscriptReviewStatus):
        invited, accepted, completed = self.aggregate_status(status)

        subject = (
            f"Your manuscript '{status.manuscript_title}' has received a review update."
        )

        content = (
            f"<h1>Manuscript Review Update</h1>"
            f"<div><b>Invited reviewers:</b> {invited}</div>"
            f"<div><b>Accepted reviewers:</b> {accepted}</div>"
            f"<div><b>Completed reviews:</b> {completed}</div>"
        )
        send_smtp_email = brevo_python.SendSmtpEmail(
            to=self.to, sender=self.sender, html_content=content, subject=subject
        )

        self.brevo.send_transac_email(send_smtp_email)
        receiver_names = [r["name"] for r in self.to]
        logger.info(f"Email sent to: {', '.join(receiver_names)}")


class ManuscriptMonitor:
    def __init__(self, uuid, mongo_conn_string):
        self.uuid = uuid
        self.client = MongoClient(mongo_conn_string, server_api=ServerApi("1"))
        self.db = self.client["manuscript_tracking"]
        self.collection = self.db[uuid]

    def get_last_known_status(self):
        return self.collection.find_one({}, {"_id": False}, sort=[("last_updated", -1)])

    def clear_collection(self):
        self.collection.delete_many({})
        logger.warning("Collection cleared")

    def get_manuscript_status(self) -> ManuscriptReviewStatus:
        endpoint = API_BASE.format(uuid=self.uuid)
        response = requests.get(endpoint)
        response.raise_for_status()

        return ManuscriptReviewStatus(**response.json())

    def check_for_updates(self, handle_status_cb):
        last_known = self.get_last_known_status()
        current = self.get_manuscript_status()

        if last_known is None:
            self.collection.insert_one(current.model_dump(by_alias=True))
            logger.info("Initial status added to the collection")
            handle_status_cb(current)
            return

        last_known = ManuscriptReviewStatus(**last_known)
        if last_known.last_updated < current.last_updated:
            self.collection.delete_one({"last_updated": last_known.last_updated})
            self.collection.insert_one(current.model_dump(by_alias=True))
            logger.info("New status added to the collection")
            handle_status_cb(current)
            return

        logger.info("No new status found")


def main():
    receiver_tuples = environ["RECEIVERS"].split("|")
    names = [r.split(":")[0] for r in receiver_tuples]
    emails = [r.split(":")[1] for r in receiver_tuples]
    receivers = [{"name": name, "email": email} for name, email in zip(names, emails)]

    MONGO_CONN_STRING = environ["MONGO_CONN_STRING"]
    m = ManuscriptMonitor(environ["MANUSCRIPT_ID"], MONGO_CONN_STRING)
    notifier = EmailNotifier(
        brevo_api_key=environ["BREVO_API_KEY"],
        sender={"name": environ["SENDER_NAME"], "email": environ["SENDER_EMAIL"]},
        to=receivers,
    )
    m.check_for_updates(notifier)
