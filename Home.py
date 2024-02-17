from datetime import datetime, timedelta
import json
import os
from random import randrange
from supabase import create_client, Client

import re
import streamlit as st
from dotenv import load_dotenv

from src.update import update_menu, notify_users

load_dotenv(".env.local")
load_dotenv()


url: str = os.environ.get("SUPABASE_URL")
key: str = os.environ.get("SUPABASE_SERVICE_KEY")
supabase: Client = create_client(url, key)

st.set_page_config(
    page_title="Penn Dining Alert",
    page_icon=":hamburger:",
    layout="wide",
    initial_sidebar_state="auto",
)

st.title("Penn Dining Alert")

home, admin = st.tabs(["Home", "Admin"])

users = supabase.table("user").select("*").execute().data
date = supabase.table("state").select("value").eq("key", "date").execute().data
menu = supabase.table("state").select("value").eq("key", "menu").execute().data


def parse_menu(data):
    dining_halls = {}
    # Iterate through each dining hall
    for hall_name, hall_info in data.items():
        items = set(hall_info["menus"]["items"].keys())
        # Initialize an empty list to hold food items for the current dining hall
        food_items = []
        if "menus" not in hall_info or hall_info["menus"] is None:
            continue
        # Iterate through each day in the menus
        for day in hall_info["menus"]["days"]:
            # Iterate through each cafe in the day
            for cafe_id, cafe_info in day["cafes"].items():
                # Extract the dining hall name (if not already done)
                if hall_name not in dining_halls:
                    dining_halls[hall_name] = []
                # Iterate through each daypart (e.g., Brunch, Dinner)
                for daypart in cafe_info["dayparts"]:
                    for dp in daypart:
                        if dp["label"] != "Dinner":
                            continue
                        # Iterate through each station in the daypart
                        for station in dp["stations"]:
                            # Add each food item's label in the station to the food_items list
                            for item_id in station["items"]:
                                # Assuming the item's detailed information is in the 'items' dictionary at the top level
                                if item_id in items:
                                    item = hall_info["menus"]["items"][item_id]
                                    # Select label, description, short_name, and nutrition keys
                                    filtered_item = {
                                        k: item[k]
                                        for k in [
                                            "label",
                                            "ingredients",
                                            "station",
                                        ]
                                    }
                                    bad_station = ["<strong>@salads</strong>", "<strong>@beverages</strong>", "<strong>@hand fruit</strong>", "<strong>@breads and bagels</strong>", "<strong>@flavors</strong>", "<strong>@salad_bar</strong>", "<strong>@coffee</strong>", "<strong>@fruit and yogurt</strong>"]
                                    if filtered_item["station"] in bad_station:
                                        continue
                                    food_items.append(filtered_item)
        dining_halls[hall_name].extend(food_items)
    return dining_halls


def update_time():
    global date, menu
    # https://stackoverflow.com/questions/553303/generate-a-random-date-between-two-other-dates
    delta = datetime(2024, 2, 10) - datetime(2024, 1, 20)
    int_delta = (delta.days * 24 * 60 * 60) + delta.seconds
    date = datetime(2024, 1, 10) + timedelta(seconds=randrange(int_delta))
    menu = update_menu(date)
    supabase.table("state").upsert(
        {"key": "date", "value": date.strftime("%Y-%m-%d %H:%M:%S.%f")}
    ).execute()
    supabase.table("state").upsert({"key": "menu", "value": json.dumps(menu)}).execute()
    notify_users(parse_menu(menu), users)


if len(date) == 0:
    # supabase.table('state').upsert({'key': 'date', 'value': '2021-08-01'}).execute()
    update_time()
else:
    date = datetime.strptime(date[0]["value"], "%Y-%m-%d %H:%M:%S.%f")

if len(menu) != 0:
    menu = json.loads(menu[0]["value"])

with home:
    with st.form(key="form"):
        st.write("Enter your phone number to receive updates")
        email = st.text_input("Email Address")
        preferences = st.text_area("Dining Preferences")
        submit = st.form_submit_button("Submit")
        if submit:
            # check if email is valid using regex
            if not email:
                st.error("Please enter your email address")
                st.stop()
            if not re.match(
                r"\b[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Z|a-z]{2,7}\b", email
            ):
                st.error("Please enter a valid email address")
                st.stop()
            if not preferences:
                st.error("Please enter your dining preferences")
                st.stop()
            supabase.table("user").upsert(
                {"email": email, "preferences": preferences}
            ).execute()
            users = supabase.table("user").select("*").execute().data
            st.write(
                "Thank you for signing up! You will receive updates on the availability of dining halls."
            )
    existing_email = st.text_input(
        "If you already registered...", placeholder="Enter your email address"
    )
    if st.button("Send me today's menu updates"):
        if existing_email == "":
            st.error("Please fill in your email above")
            st.stop()
        user = (
            supabase.table("user")
            .select("*")
            .eq("email", existing_email)
            .execute()
            .data
        )
        if len(user) == 0:
            st.error("Please sign up before requesting updates")
            st.stop()
        notify_users(parse_menu(menu), user)

with admin:
    pw = st.text_input("Enter the admin password", type="password")
    if pw == os.environ.get("ADMIN_PASSWORD"):
        st.write(date)
        if st.button("Randomize / Advance Date"):
            update_time()
            st.write("Date updated")
        if st.button("Send Update to All Users"):
            notify_users(parse_menu(menu), users)
        st.write(users)
        st.write(parse_menu(menu))
