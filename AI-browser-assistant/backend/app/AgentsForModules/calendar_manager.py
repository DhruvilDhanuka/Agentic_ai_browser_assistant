from app.AgentsForModules.pendingAnswers import register_question, get_answer
from langchain.tools import tool
from langchain_classic.agents import AgentExecutor, create_react_agent
from langchain_classic.memory import ConversationBufferMemory
from langchain_classic.prompts import PromptTemplate
from langchain_google_genai import ChatGoogleGenerativeAI
from google import genai
from google.genai import types as genai_types
import base64
from email.mime.text import MIMEText
from quickstartCalendar import get_calendar_service, get_gmail_service
import json
import os
from sqlalchemy.orm.attributes import flag_modified
from app.database import SessionLocal
from app.models_db.UserProfile import UserProfile
from app.models_db.Commands import Commands
from datetime import datetime, timedelta, timezone
from app.models_db.gmail_creds import GmailCredentials, ContactGroup
from dotenv import load_dotenv
load_dotenv()


GEMINI_API_KEY = os.getenv("GEMINI_API_KEY")


class CalendarManager:

    # We assume that the users day will begin from 9am and end at 9pm, and we will only schedule events within this time frame. We will also assume that the user is in a single timezone, and we will not handle timezone conversions for now. We will also assume that the user has a single primary calendar, and we will not handle multiple calendars for now.
    def __init__(self):
        self.executor = None
        self.user_id = None
        self.task_id = None

    def _fetch_busy_intervals(self, start_date: datetime, end_date: datetime) -> list[dict]:
        """
        Fetch every event's (start, end) between start_date and end_date,
        as a sorted list of timezone-aware datetime tuples.
        """
        service = get_calendar_service()

        # Calendar API wants RFC3339 timestamps. isoformat() on a
        # timezone-aware datetime already produces this format directly.
        time_min = start_date.isoformat()
        time_max = end_date.isoformat()

        events_result = service.events().list(
            calendarId="primary",       # the user's main calendar
            timeMin=time_min,
            timeMax=time_max,
            singleEvents=True,          # expands recurring events into individual instances
            orderBy="startTime",        # requires singleEvents=True to be valid
        ).execute()

        events = events_result.get("items", [])

        busy_intervals = []
        for event in events:
            start_raw = event["start"]
            end_raw = event["end"]

            # An event's start/end is EITHER "dateTime" (a timed event) OR
            # "date" (an all-day event, no time component). Both can appear
            # in the same response, so both need handling.
            if "dateTime" in start_raw:
                start = datetime.fromisoformat(start_raw["dateTime"])
                end = datetime.fromisoformat(end_raw["dateTime"])
            else:
                # all-day event — treat as blocking the entire day
                day_start = datetime.fromisoformat(start_raw["date"])
                day_end = datetime.fromisoformat(end_raw["date"])
                start = day_start.replace(tzinfo=start_date.tzinfo)
                end = day_end.replace(tzinfo=start_date.tzinfo)

            busy_intervals.append({
                "start": start,
                "end": end,
                "summary": event.get("summary", "Untitled event"),
                "is_all_day": "dateTime" not in start_raw,
            })

        busy_intervals.sort(key=lambda interval: interval["start"])
        return busy_intervals

    def _find_free_slots(self, busy_intervals: list[dict], start_date: datetime, end_date: datetime, slot_duration: timedelta) -> list[tuple[datetime, datetime]]:
        """
        Given a list of busy intervals, find all free slots of at least
        slot_duration between start_date and end_date.
        Returns a list of (start, end) tuples for each free slot.
        """
        free_slots = []
        current_start = start_date

        for intervalDict in busy_intervals:
            busy_start = intervalDict["start"]
            busy_end = intervalDict["end"]
            if current_start < busy_start:
                if busy_start-current_start >= slot_duration:
                    free_slots.append((current_start, busy_start))
            current_start = max(current_start, busy_end)

        if end_date - current_start >= slot_duration:
            free_slots.append((current_start, end_date))

        return free_slots

    def _append_status(self, message: str):

        db = SessionLocal()

        try:
            userCommand = db.query(Commands).filter(
                Commands.task_id == self.task_id).first()

            if (userCommand is None):
                return

            statusList = userCommand.status or []
            statusList.append(message)
            userCommand.status = statusList
            flag_modified(userCommand, "status")
            db.commit()
        finally:
            db.close()

    def _create_rrule_string(self, params: dict) -> str | None:
        """
        params: {"recurring": bool, "FREQ": str|None, "BYDAY": list[str]|None,
                "UNTIL": str|None, "COUNT": int|None, "INTERVAL": int|None}
        Returns an RRULE string, or None if not recurring.
        """
        if not params.get("recurring"):
            return None

        if params.get("COUNT") is not None and params.get("UNTIL") is not None:
            raise ValueError("COUNT and UNTIL cannot both be set")

        parts = [f"FREQ={params['FREQ']}"]

        if params.get("INTERVAL") is not None:
            parts.append(f"INTERVAL={params['INTERVAL']}")

        if params.get("BYDAY") is not None:
            parts.append(f"BYDAY={','.join(params['BYDAY'])}")

        if params.get("COUNT") is not None:
            parts.append(f"COUNT={params['COUNT']}")
        elif params.get("UNTIL") is not None:
            until_dt = datetime.fromisoformat(params["UNTIL"])
            until_utc = until_dt.astimezone(timezone.utc)
            parts.append(f"UNTIL={until_utc.strftime('%Y%m%dT%H%M%SZ')}")
        return "RRULE:" + ";".join(parts)

    def _find_clashes(self, busy_intervals: list[dict]) -> list[tuple[dict, dict]]:
        """
        Given a list of busy intervals, find all pairs of events that overlap.
        Returns a list of tuples (event1, event2) for each clash.
        """
        clashes = []
        n = len(busy_intervals)

        for i in range(n-1):
            current = busy_intervals[i]
            next_event = busy_intervals[i+1]

            if current["end"] > next_event["start"]:
                clashes.append((current, next_event))

        return clashes

    def _add_event_to_calendar(self, title: str, start: str, end: str, recurrence_params: dict | None = None, reminder_minutes: int | None = None) -> dict:
        """
        Add an event to the user's primary calendar.
        start and end are ISO 8601 strings.
        recurrence_params is a dict with keys like "FREQ", "BYDAY", "UNTIL", etc.
        reminder_minutes is the number of minutes before the event to set a reminder.
        Returns the created event object.
        """
        service = get_calendar_service()

        event_body = {
            "summary": title,
            "start": {"dateTime": start},
            "end": {"dateTime": end},
            "reminders": {
                "useDefault": False,
                "overrides": [{"method": "popup", "minutes": reminder_minutes}] if reminder_minutes is not None else []
            }
        }

        if recurrence_params:
            rrule_string = self._create_rrule_string(recurrence_params)
            if rrule_string:
                event_body["recurrence"] = [rrule_string]

        created_event = service.events().insert(
            calendarId="primary",
            body=event_body
        ).execute()

        return {
            "id": created_event.get("id"),
            "summary": created_event.get("summary"),
            "start": created_event.get("start"),
            "end": created_event.get("end"),
            "htmlLink": created_event.get("htmlLink"),
        }

    def _pick_reminder_minutes(self, title: str, recurring: bool) -> int:
        """Return how many minutes before the event to remind, based on simple keyword heuristics."""
        lowered = title.lower()
        if any(word in lowered for word in ["deadline", "due", "submission", "apply"]):
            return 24 * 60  # 1 day before — deadlines need lead time to act
        if recurring:
            return 10  # recurring habits/study blocks — just a nudge
        return 30  # default for a normal one-off event

    def setup(self, user_id: int, task_id: int):
        self.user_id = user_id
        self.task_id = task_id

        self.llm = ChatGoogleGenerativeAI(
            model="gemini-2.5-flash",
            google_api_key=GEMINI_API_KEY,
        )

        db = SessionLocal()
        try:
            user_profile = db.query(UserProfile).filter(
                UserProfile.id == user_id).first()
            self.sender_name = user_profile.Name if user_profile else "the user"

            groups_row = db.query(ContactGroup).filter(
                ContactGroup.user_id == user_id).first()
            self.groups = groups_row.groups_with_number if groups_row else {}
        finally:
            db.close()

        @tool
        def update_status(status: str) -> str:
            """Log a status update visible to the user in real time."""
            self._append_status(status)
            return "Status updated"

        @tool
        def list_events_tool(range_json: str) -> str:
            """List calendar events with their titles in a date range, so you can reason about clashes/nesting yourself.
            Input: JSON string {"start": "<ISO datetime>", "end": "<ISO datetime>"}.
            Returns JSON list of {start, end, summary, is_all_day}."""
            params = json.loads(range_json)
            start_date = datetime.fromisoformat(params["start"])
            end_date = datetime.fromisoformat(params["end"])

            events = self._fetch_busy_intervals(start_date, end_date)
            self._append_status(
                f"Fetched {len(events)} events between {start_date.date()} and {end_date.date()}")

            return json.dumps([
                {"start": e["start"].isoformat(), "end": e["end"].isoformat(),
                 "summary": e["summary"], "is_all_day": e["is_all_day"]}
                for e in events
            ])

        @tool
        def find_free_slots_tool(query_json: str):
            """Find free time slots in a date range.
            Input: JSON string {"start": "<ISO datetime>", "end": "<ISO datetime>", "duration_minutes": <int>}.
            Returns JSON list of {start, end} candidate slots, earliest first."""

            params = json.loads(query_json)
            start_date = datetime.fromisoformat(params["start"])
            end_date = datetime.fromisoformat(params["end"])
            duration = timedelta(minutes=params["duration_minutes"])

            busy = self._fetch_busy_intervals(start_date, end_date)
            slots = self._find_free_slots(busy, start_date, end_date, duration)
            self._append_status(
                f"Found {len(slots)} candidate slot(s) of {params['duration_minutes']} min")

            return json.dumps([{"start": s.isoformat(), "end": e.isoformat()} for s, e in slots])

        @tool
        def add_event(event_json: str) -> str:
            """Add an event to the user's primary calendar.
            Input: JSON string {"title": str, "start": "<ISO datetime>", "end": "<ISO datetime>", "recurrence_params": {...}|null}.
            recurrence_params, if present, needs "recurring": true plus FREQ/BYDAY/UNTIL/COUNT/INTERVAL as designed."""
            params = json.loads(event_json)
            title = params["title"]
            start = params["start"]
            end = params["end"]
            recurrence_params = params.get("recurrence_params")
            reminder_minutes = self._pick_reminder_minutes(
                title, recurrence_params is not None)

            recurrence_dict = json.loads(
                recurrence_params) if recurrence_params else None
            event = self._add_event_to_calendar(
                title, start, end, recurrence_dict, reminder_minutes)
            self._append_status(
                f"Added event '{title}' from {start} to {end}")
            return json.dumps(event)

        @tool
        def ask_user_tool(agent_query: str) -> str:
            """Ask the user a clarifying question when something is ambiguous or missing —
            e.g. an unclear time, a missing duration, which event to modify, or an
            unspecified date range. Input is the question to ask, as plain text.
            Returns the user's answer as plain text."""

            self._append_status(
                f"ASKING_USER::{agent_query}")

            event = register_question(self.task_id)
            event.wait()
            answer = get_answer(self.task_id)
            self._append_status(f"User answered: {answer}")
            return answer

        @tool
        def fetch_clashes_tool(range_json: str) -> str:
            """Fetch all pairs of events that overlap in a date range.
            Input: JSON string {"start": "<ISO datetime>", "end": "<ISO datetime>"}.
            Returns JSON list of tuples [{event1}, {event2}] for each clash."""
            params = json.loads(range_json)
            start_date = datetime.fromisoformat(params["start"])
            end_date = datetime.fromisoformat(params["end"])

            print(
                f"[DEBUG]======== fetch_clashes_tool called with range {start_date} to {end_date}")

            busy = self._fetch_busy_intervals(start_date, end_date)
            clashes = self._find_clashes(busy)
            self._append_status(
                f"Found {len(clashes)} clash(es) between {start_date.date()} and {end_date.date()}")

            return json.dumps([
                [
                    {"start": e1["start"].isoformat(), "end": e1["end"].isoformat(),
                     "summary": e1["summary"], "is_all_day": e1["is_all_day"]},
                    {"start": e2["start"].isoformat(), "end": e2["end"].isoformat(),
                     "summary": e2["summary"], "is_all_day": e2["is_all_day"]}
                ]
                for e1, e2 in clashes
            ])

        tools = [add_event, find_free_slots_tool,
                 list_events_tool, update_status, ask_user_tool, fetch_clashes_tool]

        memory = ConversationBufferMemory(
            memory_key="chat_history", return_messages=False)

        template = """
            You are a calendar assistant. You find free time, create events (including recurring ones), summarize schedules, and flag conflicts — using the user's real Google Calendar data, never assumptions.
            CONTEXT
            - The current date/time is given at the start of the Task below. Use it to resolve every relative phrase ("tomorrow", "this week", "next 2 weeks", "next Monday") into concrete ISO date ranges yourself before calling any tool. Never ask the user what "tomorrow" means.
            - Always compute ISO datetimes with the same timezone offset as the current date/time given to you. Never ask the user for a timezone.
            - Assume the user's day runs 9am–9pm unless they state otherwise — but if their command clearly implies personal/leisure time outside that (gaming, a side project, a late class), don't force it into the range .if the task is something professional like a meeting or a extra class or something like this use the 9am to 9pm range ; use the range implied by the command instead.
            -every output should be clean not just the string format returned by any of the tools it should be readable by humans easily 

            READING THE SCHEDULE
            - "What do I have scheduled tomorrow / this week" → list_events_tool for that exact range, then summarize in prose — group by day if the range is more than one day. Never dump raw JSON as your answer.
            - "What's my week looking like" (agenda digest) → list_events_tool for the week, then produce a clean day-by-day digest.
            - "Check for clashing events" → check_clashes_tool for the stated range. If clashes exist, describe each pair plainly (what overlaps with what, and when). If none, say so clearly — don't invent a clash.

            FINDING FREE TIME
            - "What's my next free slot" / "find me an hour tomorrow" → find_free_slots_tool once for the relevant range and duration; return the first result.
            - "Suggest N slots" → find_free_slots_tool once for the full window; then YOU select and present N candidates from what it returns. Do not call the tool multiple times to "search more" — one call gives you every valid gap.
            - If a preference is stated ("avoid mornings", "afternoons only", "not too late"), filter the tool's returned slots yourself before presenting — find_free_slots_tool only understands date range and duration, it does not know about preferences. Never pass a preference into the tool's input.

            CREATING EVENTS
            - Use add_event_tool for any new event, one-off or recurring.
            - For recurring events ("daily for 2 weeks", "every weekday until Friday", "every Monday and Wednesday"), extract the plain pattern (frequency, count or end date, specific days) into add_event_tool's FREQ/INTERVAL/BYDAY/COUNT/UNTIL fields. NEVER construct or write RRULE syntax yourself — the tool builds the correct RRULE string from these plain fields. Never set both COUNT and UNTIL on the same event.
            - Before creating an event, check for likely conflicts using check_clashes_tool or list_events_tool over the event's time range. If a clash is found, summarize it clearly and ask the user if they want to proceed or cancel. If no clash, proceed to create the event.
            - No confirmation step is needed before creating an event — create it directly once you have enough information.

            
            CONTEXT-AWARE CREATION
            - If the task mentions details that imply an event from something else happening (e.g. "I saw this event has a deadline on this page", a date/time surfaced by another module), use those details directly to build the event rather than asking the user to repeat them.

            WHEN INFORMATION IS MISSING
            - If a date, time, duration, or which specific event to act on is genuinely ambiguous or missing, use ask_user_tool to ask directly. Do not guess or invent a specific time/date that wasn't given or clearly implied.

            STATUS AND FINAL ANSWER
            - After every meaningful step (fetching events, finding slots, creating an event, detecting clashes), call update_status with a short, human-readable description of what just happened.
            - Your Final Answer must always be clean, readable prose a person would want to read — a summary, a confirmation with the event's link, or a clear list of options. Never return raw tool output (JSON) as your Final Answer.

            CURRENT TIME IS - {current_time}
            You have access to the following tools:
            {tools}

            Use the following format:
            Question: the input question you must answer
            Thought: you should always think about what to do
            Action: the action to take, should be one of [{tool_names}]
            Action Input: the input to the action
            Observation: the result of the action
            ... (this Thought/Action/Action Input/Observation can repeat N times)
            Thought: I now know the final answer
            Final Answer: the final answer to the original input question

            Previous conversation history:
            {chat_history}

            Begin!

            Question: {input}
            Thought:{agent_scratchpad}

        """

        prompt = PromptTemplate.from_template(template).partial(
            current_time=lambda: datetime.now().isoformat())

        agent = create_react_agent(self.llm, tools, prompt)

        self.executor = AgentExecutor(
            agent=agent,
            tools=tools,
            verbose=True,
            max_iterations=10,
            handle_parsing_errors=True,
            memory=memory,
        )

    def run(self, user_id: int, task_id: int, user_input: str) -> str:
        if self.executor is None:
            self.setup(user_id, task_id)
        now = datetime.now().astimezone()
        offset_str = now.strftime("%z")  # e.g. "+0530"
        offset_formatted = f"{offset_str[:3]}:{offset_str[3:]}"  # "+05:30"

        full_input = (
            f"Current date/time: {now.isoformat()}\n"
            f"Timezone offset to use for EVERY datetime you produce: {offset_formatted}\n"
            f"(e.g. today at midnight is: {now.strftime('%Y-%m-%d')}T00:00:00{offset_formatted})\n\n"
            f"Task: {user_input}"
        )

        result = self.executor.invoke({"input": full_input})
        self._append_status(f"Summary: {result['output']}")

        return result["output"]
