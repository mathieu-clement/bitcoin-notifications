#!/usr/bin/env python3

import asyncio
from datetime import datetime
from dateutil import tz
from email.encoders import encode_base64
from email.mime.base import MIMEBase
from email.mime.text import MIMEText
from email.mime.multipart import MIMEMultipart
import json
import logging
import requests
import smtplib
import time
import websockets

#logging.basicConfig(level=logging.DEBUG)
logging.basicConfig()
logger = logging.getLogger('transaction-listener')
logger.setLevel(logging.DEBUG)

SERVER = 'wss://ws.blockchain.info/inv'
BITCOIN_ADDR = '17EBXubB23UsDJ7oknryQHHWT7NejttQZy' # crimenetwork.co
TIMEZONE = 'America/Los_Angeles'
SMTP_SERVER = 'localhost'
SMTP_USER = 'email-user'
SMTP_PASSWORD = 'password'
SMTP_FROM = 'Bitcoin Notifier <no-reply@your-domain.tld>'
SMTP_TO = 'recipient-email@address.here'

def epoch_to_formatted_local_time(epoch):
    from_zone = tz.gettz('UTC')
    to_zone = tz.gettz(TIMEZONE)
    utc = datetime.utcfromtimestamp(epoch)
    pacific = utc.replace(tzinfo=from_zone).astimezone(to_zone)
    return pacific.strftime('%m/%d/%Y at %I:%M %p %Z')


def send_email(subject, body, json):
    logger.debug('SMTP - Connecting to server')
    smtp = smtplib.SMTP(SMTP_SERVER)
    try:
        logger.debug('SMTP - Start TLS')
        smtp.starttls()
        logger.debug('SMTP - Login')
        smtp.login(SMTP_USER, SMTP_PASSWORD)

        msg_body = MIMEText(body, 'plain')
        msg = MIMEMultipart()
        msg.attach(msg_body)
        attachment = MIMEBase('application', 'json')
        attachment.set_payload(json)
        encode_base64(attachment)
        attachment.add_header('Content-Disposition', 'attachment', filename='transaction.json')
        msg.attach(attachment)
        msg['Subject'] = subject
        msg['From'] = SMTP_FROM
        msg['To'] = SMTP_TO

        logger.debug('SMTP - Sending email, subject: "%s", body: "%s"', subject, body)
        smtp.send_message(msg)
        logger.info('SMTP - Sent email subject: "%s", body: "%s"', subject, body)
    finally:
        logger.debug ('SMTP - Quit')
        smtp.quit()


def to_dollars(bitcoins):
    r = requests.get('https://blockchain.info/ticker')
    j = r.json()
    rate = j['USD']['last']
    dollars = float(rate) * bitcoins
    return round(dollars, 2)


async def main():
    async with websockets.connect(SERVER) as websocket:
        # Subscribe to transactions
        await websocket.send(json.dumps({
            'op': 'addr_sub',
            'addr': BITCOIN_ADDR
            }))
#        await websocket.send(json.dumps({'op':'ping_tx'}))
        
        while True:
            transaction = json.loads( await websocket.recv() )
            logger.info('Received transaction') 
            transaction_json = json.dumps(transaction, indent=4)
            logger.debug(transaction_json)
            epoch = transaction['x']['time']
            logger.info('Local time: %s', epoch_to_formatted_local_time(epoch))

            # Find the "out" part of the transaction
            #is_credit = 'out' in transaction['x'] and any(list(map(lambda f: f['addr'] == BITCOIN_ADDR, transaction['out'])))
            value = None # bitcoins
            tr = None
            for out_transaction in transaction['x']['out']:
                addr = out_transaction['addr']
                if addr == BITCOIN_ADDR:
                    value = float(out_transaction['value'])/100000000.0
                    tr = out_transaction
                    break

            if value is not None:
                # if we received money
                logger.debug("Found an \"in\" transaction: %s", json.dumps(tr, indent=4))
                logger.info("Received %f bitcoins", value)
                dollars = 0.0
                subject = ''
                try:
                    dollars = to_dollars(value)
                    subject = 'Received %f BTC (%f USD)' % (value, dollars)
                except: 
                    logger.warn('Could not convert to dollars')
                    subject = 'Received %f BTC' % (value,)
                send_email(subject, 'Moneyyy!', transaction_json)
            elif 'inputs' in transaction['x']:
                # if we spent money
                out_value = None
                out_tr = None
                for in_transaction in transaction['x']['inputs']:
                    addr = in_transaction['prev_out']['addr']
                    if addr == BITCOIN_ADDR:
                        value = float(in_transaction['prev_out']['value'])/100000000.0
                        tr = in_transaction
                        break

                if out_value is not None:
                    logger.debug("Found an \"out\" transaction: %s", json.dumps(out_tr, indent=4))
                    logger.info("Send %f bitcoins", out_value)
                    dollars = 0.0
                    subject = ''
                    try:
                        dollars = to_dollars(out_value)
                        subject = 'Sent %f BTC (%f USD)' % (out_value, dollars)
                    except:
                        logger.warn('Could not convert to dollars')
                        subject = 'Sent %f BTC' % (out_value,)
                    send_email(subject, 'Money left the bitcoin wallet', transaction_json)

if __name__ == '__main__':
    asyncio.get_event_loop().run_until_complete(main())
