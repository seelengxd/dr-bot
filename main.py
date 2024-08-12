
from telegram.ext import Application, CommandHandler, ContextTypes, MessageHandler, filters
from telegram import ForceReply, Update
import logging
from enum import Enum
from datetime import datetime, timedelta
import requests
from bs4 import BeautifulSoup
import dotenv
import os
import pytz

dotenv.load_dotenv()

TOKEN = os.getenv("TOKEN")


class Room(str, Enum):
    """The six rooms I care about"""
    DR6 = "DR6"
    DR7 = "DR7"
    DR8 = "DR8"
    DR9 = "DR9"
    DR10 = "DR10"
    DR11 = "DR11"


LOCATION = {
    Room.DR6: "COM2-02-12",
    Room.DR7: "COM2-03-14",
    Room.DR8: "COM2-03-30",
    Room.DR9: "COM2-04-06",
    Room.DR10: "COM2-02-24",
    Room.DR11: "COM2-02-23"
}

# Scrape room data
sgt = pytz.timezone("Asia/Singapore")


def get_url(room: Room, date_raw: str | datetime):
    if isinstance(date_raw, str):
        date = datetime.strftime(date_raw, "%Y/%m/%d")
    else:
        date = date_raw
    date = date.strftime("%Y/%m/%d")
    return f"https://mysoc.nus.edu.sg/~calendar/getBooking.cgi?room={room.removeprefix('Room.')}&thedate={date}"


def process_time(date: datetime, time: str):
    result = datetime.strptime(time, "%I:%M%p")
    result = result.replace(year=date.year, month=date.month, day=date.day)
    return sgt.localize(result)


def scrape_room(room: Room, date: datetime):
    soup = BeautifulSoup(requests.get(get_url(room, date)
                                      ).content, features="html.parser")

    all_tr = soup.find_all("tr")
    content = [[td.text for td in tr.contents] for tr in all_tr]

    processed = []
    for row in content:
        if row[0] == "No bookings made.":
            continue
        slot, reason = row
        start, end = slot.split(" - ")
        start = process_time(date, start)
        end = process_time(date, end)
        processed.append(((start, end), reason))
    return processed


def get_availability(data):
    now = datetime.now(sgt)
    booked = False
    until = None
    for ((start, end), _) in data:
        # Bookings in the past are irrelevant.
        if end < now:
            continue
        # If there is a booking now, I can't use it.
        if start <= now <= end:
            booked = True
            until = end
            continue
        # If it was free, the first future booking makes it "busy"
        if not booked:
            until = start
            break
        if booked:
            # If the booking is continuous, extend the busy time.
            if start == until:
                until = end
            else:
                break

    return booked, until


def query_today():
    # Scrape today's data
    today = datetime.now(sgt)
    data = {room: {"bookings": scrape_room(room, today)} for room in Room}

    for room in data:
        booked, until = get_availability(data[room]["bookings"])
        data[room]["booked"] = booked
        data[room]["until"] = until

    return data


# Enable logging
logging.basicConfig(
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s", level=logging.INFO
)
# set higher logging level for httpx to avoid all GET and POST requests being logged
logging.getLogger("httpx").setLevel(logging.WARNING)

logger = logging.getLogger(__name__)

HELP_TEXT = """
/help - Shows this text
/all - Shows which rooms are booked/available
/one <room> - Shows why the room is booked, options: DR6, DR7, DR8, DR9, DR10, DR11
"""

# Define a few command handlers. These usually take the two arguments update and
# context.


async def start(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Send a message when the command /start is issued."""
    user = update.effective_user
    await update.message.reply_html(
        rf"Hi {user.mention_html()}!",
    )


async def query_all(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Send a message when the command /help is issued."""

    data = query_today()
    result = sgt.localize(datetime.today()).strftime("__%d %b__\n")
    for room in data:
        room_data = data[room]
        booked_label = 'Booked' if room_data['booked'] else "Free"
        until_label = f" until {room_data['until'].strftime('%I:%M%p')}" if room_data[
            'until'] else ""
        result += f"{room.removeprefix('Room.')}: *{booked_label}*{until_label}\n"

    result = result.replace("-", "\-").replace("=", "\=").replace(".", "\.")
    await update.message.reply_text(result, parse_mode='MarkdownV2')


async def query_one(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    room = context.args[0].upper().strip() if context.args else None
    if not room:
        await update.message.reply_text(
            f"Missing room argument (/one <room>), must be one of {', '.join([room for room in Room])}.")
        return
    if room not in LOCATION:
        await update.message.reply_text(
            f"{room} is invalid: must be one of {', '.join([room for room in Room])}.")
        return
    room_data = scrape_room(room, sgt.localize(datetime.today()))
    booked, until = get_availability(room_data)

    result = f"{room} - {LOCATION[room]}\n"
    booked_label = 'Booked' if booked else "Free"
    until_label = f" until {until.strftime('%I:%M%p')}" if until else ""
    result += f"*{booked_label}*{until_label}\n"
    result += "===============\n"
    for (start, end), reason in room_data:
        result += f"{start.strftime('%I:%M%p')}-{end.strftime('%I:%M%p')}: {reason}\n"

    result = result.replace("-", "\-").replace("=", "\=").replace(".", "\.")
    await update.message.reply_text(result, parse_mode='MarkdownV2')


async def help(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Send a message when the command /help is issued."""
    await update.message.reply_text(HELP_TEXT)


def main() -> None:
    """Start the bot."""
    # Create the Application and pass it your bot's token.
    application = Application.builder().token(TOKEN).build()

    # on different commands - answer in Telegram
    application.add_handler(CommandHandler("start", start))
    application.add_handler(CommandHandler("all", query_all))
    application.add_handler(CommandHandler("one", query_one))
    application.add_handler(CommandHandler("help", help))

    # Run the bot until the user presses Ctrl-C
    application.run_polling(allowed_updates=Update.ALL_TYPES)


if __name__ == "__main__":
    main()
