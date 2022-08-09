#!/usr/bin/python3

import sys
import smtplib
import ssl
import aiohttp
from os import environ
from email.message import EmailMessage
import requests, json, datetime
import json
from os import getcwd, path
import rsa

def get_distribution_list():
    """
        Reads from ./mail_data/.distribution_list and produces list of addresses that the
        email should be sent off to. Reads only the first email in entry, ignores the rest.
    """
    from os import getcwd, path
    dpath = path.join(getcwd(), 'mail_data', '.distribution_list')
    distList = []
    with open(dpath, 'r') as dl:
        for mail in dl.readlines():
            if '@' in mail:
                # add only one per line
                distList.append(mail.split()[0].strip())
    return distList


def gmail_authenticate():
    import pickle
    from os import path
    from googleapiclient.discovery import build
    from google_auth_oauthlib.flow import InstalledAppFlow
    from google.auth.transport.requests import Request
    SCOPES = ['https://mail.google.com/']
    creds = None
    # the file token.pickle stores the user's access and refresh tokens, and is
    # created automatically when the authorization flow completes for the first time
    if path.exists("token.pickle"):
        with open("token.pickle", "rb") as token:
            creds = pickle.load(token)
    # if there are no (valid) credentials availablle, let the user log in.
    if not creds or not creds.valid:
        if creds and creds.expired and creds.refresh_token:
            creds.refresh(Request())
        else:
            flow = InstalledAppFlow.from_client_secrets_file('./mail_data/credentials.json', SCOPES)
            creds = flow.run_local_server(port=0)
        # save the credentials for the next run
        with open("token.pickle", "wb") as token:
            pickle.dump(creds, token)
    return build('gmail', 'v1', credentials=creds)


def search_messages(service, query):
    result = service.users().messages().list(userId='me', q=query).execute()
    messages = []
    if 'messages' in result:
        messages.extend(result['messages'])
    while 'nextPageToken' in result:
        page_token = result['nextPageToken']
        result = service.users().messages().list(userId='me', q=query, pageToken=page_token).execute()
        if 'messages' in result:
            messages.extend(result['messages'])
    return messages

def parse_parts(service, parts, folder_name, message):
    """
    Utility function that parses the content of an email partition
    """
    # for encoding/decoding messages in base64
    from os import path
    from base64 import urlsafe_b64decode, urlsafe_b64encode
    if parts:
        for part in parts:
            filename = part.get("filename")
            mimeType = part.get("mimeType")
            body = part.get("body")
            data = body.get("data")
            file_size = body.get("size")
            part_headers = part.get("headers")
            if part.get("parts"):
                # recursively call this function when we see that a part
                # has parts inside
                parse_parts(service, part.get("parts"), folder_name, message)
            if mimeType == "text/plain":
                # if the email part is text plain
                if data:
                    text = urlsafe_b64decode(data).decode()
                    print(text)
            elif mimeType == "text/html":
                # if the email part is an HTML content
                # save the HTML file and optionally open it in the browser
                if not filename:
                    filename = "index.html"
                filepath = path.join(folder_name, filename)
           #     print("Saving HTML to", filepath)
           #     with open(filepath, "wb") as f:
            #        f.write(urlsafe_b64decode(data))
            else:
                # attachment other than a plain text or HTML
                for part_header in part_headers:
                    part_header_name = part_header.get("name")
                    part_header_value = part_header.get("value")
                    if part_header_name == "Content-Disposition":
                        if "attachment" in part_header_value:
                            # we get the attachment ID
                            # and make another request to get the attachment itself
                            print("Saving the file:", filename, "size:", get_size_format(file_size))
                            attachment_id = body.get("attachmentId")
                            attachment = service.users().messages() \
                                .attachments().get(id=attachment_id, userId='me', messageId=message['id']).execute()
                            data = attachment.get("data")
                            filepath = path.join(folder_name, filename)
                            if data:
                                with open(filepath, "wb") as f:
                                    f.write(urlsafe_b64decode(data))

# utility functions
def get_size_format(b, factor=1024, suffix="B"):
    """
    Scale bytes to its proper byte format
    e.g:
        1253656 => '1.20MB'
        1253656678 => '1.17GB'
    """
    for unit in ["", "K", "M", "G", "T", "P", "E", "Z"]:
        if b < factor:
            return f"{b:.2f}{unit}{suffix}"
        b /= factor
    return f"{b:.2f}Y{suffix}"

def clean(text):
    # clean text for creating a folder
    return "".join(c if c.isalnum() else "_" for c in text)

def read_message(service, message):
    """
    This function takes Gmail API `service` and the given `message_id` and does the following:
        - Downloads the content of the email
        - Prints email basic information (To, From, Subject & Date) and plain/text parts
        - Creates a folder for each email based on the subject
        - Downloads text/html content (if available) and saves it under the folder created as index.html
        - Downloads any file that is attached to the email and saves it in the folder created
    """
    from os import path, mkdir
    msg = service.users().messages().get(userId='me', id=message['id'], format='full').execute()
    # parts can be the message body, or attachments
    payload = msg['payload']
    headers = payload.get("headers")
    parts = payload.get("parts")
    folder_name = "email"
    has_subject = False
    if headers:
        # this section prints email basic info & creates a folder for the email
        for header in headers:
            name = header.get("name")
            value = header.get("value")
            if name.lower() == 'from':
                # we print the From address
                print("From:", value)
                email_from = value
            if name.lower() == "to":
                # we print the To address
                print("To:", value)
            if name.lower() == "subject":
                # make our boolean True, the email has "subject"
                has_subject = True
                # make a directory with the name of the subject
                folder_name = clean(value)
                # we will also handle emails with the same subject name
                folder_counter = 0
                while path.isdir(folder_name):
                    folder_counter += 1
                    # we have the same folder name, add a number next to it
                    if folder_name[-1].isdigit() and folder_name[-2] == "_":
                        folder_name = f"{folder_name[:-2]}_{folder_counter}"
                    elif folder_name[-2:].isdigit() and folder_name[-3] == "_":
                        folder_name = f"{folder_name[:-3]}_{folder_counter}"
                    else:
                        folder_name = f"{folder_name}_{folder_counter}"
                print("Subject:", value)
            if name.lower() == "date":
                # we print the date when the message was sent
                print("Date:", value)
    if not has_subject:
        # if the email does not have a subject, then make a folder with "email" name
        # since folders are created based on subjects
        print("Subject not found.")
    parse_parts(service, parts, folder_name, message)
    return email_from.split("<")[1].replace('>', '').strip()


def delete_messages(service, query):
    messages_to_delete = search_messages(service, query)
    # it's possible to delete a single message with the delete API, like this:
    # service.users().messages().delete(userId='me', id=msg['id'])
    # but it's also possible to delete all the selected messages with one query, batchDelete
    return service.users().messages().batchDelete(
        userId='me',
        body={
            'ids': [msg['id'] for msg in messages_to_delete]
        }
    ).execute()

def check_unsubscribed(distribution_list):
    """
        Checks for incoming unsubscribe emails. Updates the .distribution_list file.
    """
    from os import path
    # Request all access (permission to read/send/receive emails, manage the inbox, and more)
    fpl_username = r'jacobsfantasypremierleague@gmail.com'
    query = r'in:inbox Unsubscribe'
    service = gmail_authenticate()
    results = search_messages(service, query)
    if not results:
        print("No unsubscribe emails found!")
        return
    for msg in results:
        try:
            from_email = read_message(service, msg)
            if '@jacobs' in from_email:
                from_email = from_email.lower()
            distribution_list.remove(from_email)
        except ValueError:
            print('User {} not in distribution list.'.format(from_email))
    with open(path.join(getcwd(), 'mail_data', '.distribution_list'), 'w') as dsl:
        for email_address in distribution_list:
            dsl.write(email_address + "\n")
    # Now, delete messages, so that if subscribe was sent through, then user is added again.
    delete_messages(service, query)

def check_update():
    """
        A function that will be triggered to distribute emails to all of the league
        participants.

        The fucntion will take todays date and compare it to the
    """
    from classic_league import BootStrap
    days_to_deadline = BootStrap().get_days_to_deadline()
    if days_to_deadline <= 1.0:
        return True, days_to_deadline
    else:
        return False, days_to_deadline


def read_email_body():
    """
        Reads data from ./mail_data/body.txt
    """
    from datetime import datetime
    to_league_start = datetime(2022, 8, 20).timestamp() - datetime.today().timestamp()
    to_league_start = round(to_league_start/86400.0, 0)
    mail_body = ""
    with open(path.join(getcwd(), 'mail_data', 'body.txt'), 'r') as bod:
        for line in bod.readlines():
            if "@league_msg" in line:
                if to_league_start > 0:
                    inline = "The league will start in {0:d} days!".format(int(to_league_start))
                else:
                    inline = "The league has now started! Good Luck everyone!"
                line = line.replace("@league_msg", inline)
            mail_body += line + "\n"
    return mail_body


def send_reminder_email(gameWeek, distribution_list, days_to_deadline):
    from pathlib import Path
    from email.mime.multipart import MIMEMultipart
    from email.mime.text import MIMEText
    from email.mime.base import MIMEBase
    from email import encoders
    hours_to_deadline = round(days_to_deadline*24.0, 0)
    fpl_username = r'jacobsfantasypremierleague@gmail.com'
    fpl_password = environ.get('FPL_GM_PASS')
    files = ['./mail_data/images/Banner.png']
    if fpl_password is None:
        raise OSError
    else:
        print("Logging in.")
    html_body = read_email_body()
    subject = "[REMINDER - ONLY {} h REMAIN] Update your team for Gameweek #{}!".format(hours_to_deadline, gameWeek)
    mail = MIMEMultipart('alternative')
    mail['From'] = fpl_username
    mail['Subject'] = subject
    mainB = MIMEText(html_body, 'html')
    mail.attach(mainB)
    for path in files:
        part = MIMEBase('application', "octet-stream")
        with open(path, 'rb') as file:
            part.set_payload(file.read())
        encoders.encode_base64(part)
        part.add_header('Content-Type', 'image/png')
        part.add_header('Content-ID', '<{}>'.format(Path(path).name))
        part.add_header('Content-Disposition',
                        'attachment; filename={}'.format(Path(path).name))
        mail.attach(part)
    for email_address in distribution_list:
        mail['To'] = email_address
        with smtplib.SMTP('smtp.gmail.com', 587) as smtp:
            smtp.ehlo()
            smtp.starttls()
            smtp.login(fpl_username, fpl_password)
            smtp.sendmail(fpl_username, email_address, mail.as_string())
            smtp.quit()


def main():
    from classic_league import BootStrap
    distribution_list = get_distribution_list()
    if not distribution_list:
        print("No one to send emails to...")
        exit(0)
    check_unsubscribed(distribution_list)
    update, days_to_deadline = check_update()
    upcoming_gw = BootStrap().get_current_gameweek() + 1
    if update:
        send_reminder_email(upcoming_gw, distribution_list, days_to_deadline)
    else:
        exit(0)


if __name__ == "__main__":
    main()
