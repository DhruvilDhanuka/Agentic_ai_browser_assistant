import os.path

from google.auth.transport.requests import Request
from google.oauth2.credentials import Credentials
from google_auth_oauthlib.flow import InstalledAppFlow
from googleapiclient.discovery import build
from googleapiclient.errors import HttpError

# If modifying these scopes, delete the file token.json.
SCOPES = [
    "https://www.googleapis.com/auth/gmail.readonly",
    "https://www.googleapis.com/auth/gmail.send",
    "https://www.googleapis.com/auth/calendar",
]


def get_credentials():
    """
    Return valid, refreshed Google OAuth credentials covering both Gmail
    and Calendar scopes, running the consent flow if needed.
    For now uses a single shared token.json (single-user setup).
    TODO: look up/store per-user credentials via a DB table (user_id -> token_json)
    instead of a flat file, once this moves to a real multi-user "Sign in with
    Google" flow.
    """
    creds = None
    if os.path.exists("token.json"):
        creds = Credentials.from_authorized_user_file("token.json", SCOPES)

    if not creds or not creds.valid:
        if creds and creds.expired and creds.refresh_token:
            try:
                creds.refresh(Request())
            except Exception:
                creds = None  # refresh token dead — fall through to a fresh consent flow

        if not creds or not creds.valid:
            flow = InstalledAppFlow.from_client_secrets_file(
                "credentials.json", SCOPES
            )
            creds = flow.run_local_server(port=0)

        with open("token.json", "w") as token:
            token.write(creds.to_json())

    return creds


def get_gmail_service():
    """Return an authenticated Gmail API service object."""
    creds = get_credentials()
    return build("gmail", "v1", credentials=creds)


def get_calendar_service():
    """Return an authenticated Google Calendar API service object."""
    creds = get_credentials()
    return build("calendar", "v3", credentials=creds)


if __name__ == "__main__":
    # Quick manual test: confirms auth works for both services in one run.
    try:
        gmail = get_gmail_service()
        labels = gmail.users().labels().list(userId="me").execute().get("labels", [])
        print(f"Gmail OK — {len(labels)} labels found.")

        cal = get_calendar_service()
        calendars = cal.calendarList().list().execute().get("items", [])
        print(f"Calendar OK — {len(calendars)} calendars found.")
    except HttpError as error:
        print(f"An error occurred: {error}")
