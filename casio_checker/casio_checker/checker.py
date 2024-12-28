import logging
from datetime import datetime
from os import environ
from urllib.parse import urlparse

import brevo_python
import requests
from bs4 import BeautifulSoup
from dotenv import load_dotenv
from pydantic import BaseModel
from pymongo import MongoClient

load_dotenv()


def init_log():
    logging.basicConfig(level=logging.INFO)
    logger = logging.getLogger("CASIO_CHECKER")
    return logger


logger = init_log()


class EmailNotifier:
    def __init__(self, brevo_api_key, sender, to):
        configuration = brevo_python.Configuration()
        configuration.api_key["api-key"] = brevo_api_key
        self.brevo = brevo_python.TransactionalEmailsApi(
            brevo_python.ApiClient(configuration)
        )
        self.to = to
        self.sender = sender

    def __call__(self, old_price, new_price):
        subject = f"Price Update for {new_price.url}"
        content = f"<h1>Price for the item you are tracking ({new_price.url})</h1>"

        if old_price is None:
            content += f"<p>Price tracking has started</p>"
            content += f"<p>Current price: {new_price.price} {new_price.currency}</p>"
        else:
            content += f"<p>Price change detected</p>"
            content += f"<p>Old price: {old_price.price} {old_price.currency}</p>"
            content += f"<p>New price: {new_price.price} {new_price.currency}</p>"
            content += f"<p><strong>Price change: {new_price.price - old_price.price} {new_price.currency}</strong></p>"

        send_smtp_email = brevo_python.SendSmtpEmail(
            to=self.to, sender=self.sender, html_content=content, subject=subject
        )

        self.brevo.send_transac_email(send_smtp_email)
        receiver_names = [r["name"] for r in self.to]
        logger.info(f"Email sent to: {', '.join(receiver_names)}")


class ProductPrice(BaseModel):
    timestamp: datetime
    price: float
    currency: str
    url: str


class MuzikerPriceChecker:
    def __init__(self, url, mongo_conn_string):
        self.url = urlparse(url, scheme="")
        self.client = MongoClient(mongo_conn_string)
        self.db = self.client[f"muziker_prices"]
        self.collection = self.db[self.url.path.replace("/", "")]

    def get_price(self):
        html = requests.get(self.url.geturl()).text
        soup = BeautifulSoup(html, "html.parser")
        price_div = soup.find("div", attrs={"data-original-price": True})
        price = price_div["data-original-price"].split(" ")

        return ProductPrice(
            timestamp=datetime.now(),
            price=float(price[0].replace(",", ".")),
            currency=price[1],
            url=self.url.geturl(),
        )

    def check_for_updates(self, handle_status_cb):
        current_price = self.get_price()

        if self.collection.count_documents({}) == 0:
            self.collection.insert_one(current_price.model_dump())
            handle_status_cb(None, current_price)
            logger.info("First price added to db")
            return

        last_known_price = (
            self.collection.find({}, {"_id": False}).sort("timestamp", -1).limit(1)[0]
        )
        self.collection.insert_one(current_price.model_dump())
        
        if last_known_price["price"] != current_price.price:
            handle_status_cb(ProductPrice(**last_known_price), current_price)
            logger.info("Price change detected")
            return
        logger.info("No price change detected")


def main():
    receiver_tuples = environ["RECEIVERS"].split("|")
    names = [r.split(":")[0] for r in receiver_tuples]
    emails = [r.split(":")[1] for r in receiver_tuples]
    receivers = [{"name": name, "email": email} for name, email in zip(names, emails)]
    notifier = EmailNotifier(
        brevo_api_key=environ["BREVO_API_KEY"],
        sender={"name": environ["SENDER_NAME"], "email": environ["SENDER_EMAIL"]},
        to=receivers,
    )
    checker = MuzikerPriceChecker(
        "https://www.muziker.bg/ct-s300", mongo_conn_string=environ["MONGO_CONN_STRING"]
    )
    checker.check_for_updates(notifier)
