#!/usr/bin/python3

def overwrite_json(json_path, json_object):
    import json
    json_file = open(json_path, 'w')
    json.dump(json_object, json_file)
    json_file.close()


def read_from_json_file(json_path):
    import json
    from os import path
    data = []
    if not path.exists(json_path):
        return data
    else:
        with open(json_path, 'r') as f:
            data = json.loads(f.read())
    return data


def json_extract(json_object, keys):
    """

    :param json_object: A list of dictionaries
    :param keys: A data fields to be extracted from the json_object
    :return: a list of found items
    """
    found = []
    for entry in json_object:
        try:
            found_entry = []
            for key in keys:
                found_entry.append(entry[key])
            if len(found_entry) == 1:
                found.append(found_entry[0])
            else:
                found.append(found_entry)
        except KeyError:
            print("ERROR: Key is not in the json_object. Try different key.")
            return []
    return found


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
    # if there are no (valid) credentials available, let the user log in.
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
    from base64 import urlsafe_b64decode
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
    from os import path
    msg = service.users().messages().get(userId='me', id=message['id'], format='full').execute()
    # parts can be the message body, or attachments
    payload = msg['payload']
    headers = payload.get("headers")
    parts = payload.get("parts")
    folder_name, email_from = "email", ""
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


def check_unsubscribed():
    """
        Checks for incoming unsubscribe emails. Updates the .distribution_list file.
    """
    # Request all access (permission to read/send/receive emails, manage the inbox, and more)
    query = r'in:inbox Unsubscribe'
    service = gmail_authenticate()
    results = search_messages(service, query)
    managers_unsubscribed = []
    from_email = ""
    if not results:
        print("No unsubscribe emails found!")
        return []
    for msg in results:
        try:
            from_email = read_message(service, msg)
            if '@jacobs' in from_email:
                from_email = from_email.lower()
            managers_unsubscribed.append(from_email)
        except ValueError:
            print('User {} not in distribution list.'.format(from_email))
    # Now, delete messages, so that if subscribe was sent through, then user is added again.
    delete_messages(service, query)
    return managers_unsubscribed


def check_update(bootstrap, fixtures, json_object):
    """
        A function that will be triggered to distribute emails to all of the league
        participants.

        The function will take today's date and compare it to the
    """
    from datetime import datetime
    gameweek_data = json_object['league_data'][1]['gameweek_info']
    days_to_deadline = bootstrap.get_days_to_deadline()
    current_gw = bootstrap.get_current_gameweek()
    upcoming_gw = current_gw + 1
    time_to_final_gw_fixture = fixtures.get_time_to_final_fixture_of_gameweek(current_gw)
    has_reminded, has_newscast = False, False
    send_reminder, send_newsletter = False, False
    # extract info on whether, or not the reminder has been sent out to the
    # users for the upcoming gameweek.
    # Also, extract the data about the current gameweek reminder for newsletter
    for gw_entry in gameweek_data:
        # for newsletter
        if gw_entry['gameweek'] == str(current_gw):
            if gw_entry['newsletter_sent'] != 'None':
                has_newscast = True
        if gw_entry['gameweek'] == str(upcoming_gw):
            if gw_entry['reminder_sent'] != 'None':
                has_reminded = True
    # update team reminder
    if days_to_deadline <= 1.0 and not has_reminded:
        send_reminder = True
        upgw_index = upcoming_gw + 1
        json_object['league_data'][1]['gameweek_info'][upgw_index]['reminder_sent'] \
            = datetime.now().strftime('%d/%M/%YT%H:%M')
    # update newsletter reminder
    if time_to_final_gw_fixture < 0.0 and not has_newscast:
        send_newsletter = True
        crgw_index = current_gw + 1
        json_object['league_data'][1]['gameweek_info'][crgw_index]['newsletter_sent'] \
            = datetime.now().strftime('%d/%M/%YT%H:%M')
    return send_reminder, send_newsletter, days_to_deadline, time_to_final_gw_fixture


def read_newsletter_email_body(league, bootstrap, players):
    """
        Reads data from ./mail_data/newsletter_body.txt
    """
    from os import getcwd, path
    # Obtain manager related data and format!
    table_of_managers = league.managers.create_manager_table(bootstrap).to_html(index=False,
                                                                                justify='center',
                                                                                )
    table_of_managers = table_of_managers.replace("[", "")
    table_of_managers = table_of_managers.replace("]", "")
    table_of_managers = table_of_managers.replace(">False, 0", " bgcolor=\"#337580\">")
    table_of_managers = table_of_managers.replace(">True, ", " bgcolor=\"#bc909a\"> Used on GW #")
    # Top 5 players on each position, based on historic data...
    top5_goalkeepers = players.get_player_data('Goalkeeper',
                                               'cost_to_points',
                                               False, 5).to_html(index=False,
                                                                 justify='center',
                                                                 float_format='{:.2f}'.format
                                                                 )
    top5_defenders = players.get_player_data('Defender',
                                             'cost_to_points',
                                             False, 5).to_html(index=False,
                                                               justify='center',
                                                               float_format='{:.2f}'.format
                                                               )
    top5_midfielders = players.get_player_data('Midfielder',
                                               'cost_to_points',
                                               False, 5).to_html(index=False,
                                                                 justify='center',
                                                                 float_format='{:.2f}'.format
                                                                 )
    top5_forwards = players.get_player_data('Forward',
                                            'cost_to_points',
                                            False, 5).to_html(index=False,
                                                              justify='center',
                                                              float_format='{:.2f}'.format
                                                              )
    mail_body = ''
    with open(path.join(getcwd(), 'mail_data', 'newsletter_body.txt'), 'r') as bod:
        for line in bod.readlines():
            if "@players_table" in line:
                line = line.replace("@players_table", table_of_managers)
            if "@gk_rec" in line:
                line = line.replace("@gk_rec", top5_goalkeepers)
            if "@def_rec" in line:
                line = line.replace("@def_rec", top5_defenders)
            if "@mid_rec" in line:
                line = line.replace("@mid_rec", top5_midfielders)
            if "@for_rec" in line:
                line = line.replace("@for_rec", top5_forwards)
            mail_body += line + "\n"
    return mail_body


def read_email_body(league):
    """
        Reads data from ./mail_data/reminder_body.txt
    """
    from datetime import datetime
    from os import getcwd, path
    to_league_start = datetime(2022, 8, 20).timestamp() - datetime.today().timestamp()
    to_league_start = round(to_league_start / 86400.0, 0)
    no_managers = league.managers.no_managers
    mail_body = ""
    with open(path.join(getcwd(), 'mail_data', 'reminder_body.txt'), 'r') as bod:
        for line in bod.readlines():
            if "@league_msg" in line:
                if to_league_start > 0:
                    inline = "The league will start in {0:d} day(s)!".format(int(to_league_start))
                else:
                    inline = "The league has now started! Good Luck everyone!"
                line = line.replace("@league_msg", inline)
            if "@registered" in line:
                line = line.replace("@registered", str(no_managers))
            mail_body += line + "\n"
    return mail_body


def send_reminder_email(distribution_list, subject, html_body, files_attached):
    from pathlib import Path
    from email.mime.multipart import MIMEMultipart
    from email.mime.text import MIMEText
    from email.mime.base import MIMEBase
    from email import encoders
    from os import environ
    import smtplib
    fpl_username = r'jacobsfantasypremierleague@gmail.com'
    fpl_password = environ.get('FPL_GM_PASS')
    files = files_attached
    if fpl_password is None:
        raise OSError
    else:
        print("Logging in.")
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
    from classic_league import ClassicLeague
    from classic_league import Players
    from classic_league import Fixtures
    from os import getcwd, path
    json_path = path.join(getcwd(), 'mail_data/.league_data.json')
    json_object = read_from_json_file(json_path)
    manager_data = json_object['league_data'][0]['manager_data']
    distribution_list = json_extract(manager_data, ['email'])
    managers_unsubscribed = check_unsubscribed()
    for unsubscribed_email in managers_unsubscribed:
        for index, entry in enumerate(manager_data):
            if entry['email'] == unsubscribed_email:
                del json_object['league_data'][0]['manager_data'][index]
                break
    league = ClassicLeague(1026637, 'Jacobs FPL S4')
    bootstrap = BootStrap()
    fixtures = Fixtures(bootstrap)
    current_gw = bootstrap.get_current_gameweek()
    upcoming_gw = current_gw + 1
    if not distribution_list:
        print("No one to send emails to...")
        overwrite_json(json_path, json_object)
        exit(0)
    send_reminder, send_newsletter, days_to_deadline, days_to_final_game = check_update(bootstrap,
                                                                                        fixtures,
                                                                                        json_object
                                                                                        )
    hours_to_deadline = round(days_to_deadline * 24.0, 0)
    # Check if update email should be sent out to the managers
    if send_reminder:
        reminder_email_body = read_email_body(league)
        subject = "REMINDER - Only {} h Remain! Update your team for the Gameweek #{}!".format(hours_to_deadline,
                                                                                               upcoming_gw
                                                                                               )
        attachments = ['./mail_data/images/Banner.png']
        send_reminder_email(distribution_list, subject, reminder_email_body, attachments)
    else:
        print("It's not yet time to sent reminder email! Days to deadline: {}.".format(days_to_deadline))
    # Check if newsletter should be sent to the managers
    if send_newsletter:
        players = Players(bootstrap)
        players.load_players_and_calculate_xp(fixtures.upcoming_fixture_data)
        newsletter_body = read_newsletter_email_body(league, bootstrap, players)
        subject = "Newsletter for Jacobs FPL Gameweek #{}".format(bootstrap.get_current_gameweek())
        attachments = ['./mail_data/images/Newsletter_Banner.png']
        send_reminder_email(distribution_list, subject, newsletter_body, attachments)
    else:
        print("It's not yet time to sent newsletter email! "
              "Days to/since final GW fixture: {}".format(days_to_final_game / 86400.0))
    overwrite_json(json_path, json_object)


if __name__ == "__main__":
    main()
