import json
import os
from time import sleep
import requests
from datetime import datetime, timedelta
from supabase import create_client, Client
import sendgrid
from sendgrid.helpers.mail import Mail, Email, To, Content
from langchain_community.chat_models.anyscale import ChatAnyscale
from langchain.schema import HumanMessage, SystemMessage

import streamlit as st
from dotenv import load_dotenv

load_dotenv(".env.local")
load_dotenv()

url: str = os.environ.get("SUPABASE_URL")
key: str = os.environ.get("SUPABASE_SERVICE_KEY")
supabase: Client = create_client(url, key)

OPEN_DATA_URL = "https://3scale-public-prod-open-data.apps.k8s.upenn.edu/api/v1/dining/"
OPEN_DATA_ENDPOINTS = {
    "VENUES": OPEN_DATA_URL + "venues",
    "MENUS": OPEN_DATA_URL + "menus",
}
OPENID_ENDPOINT = (
    "https://sso.apps.k8s.upenn.edu/auth/realms/master/protocol/openid-connect/token"
)

token: str = None
expiration = datetime.now()

llm = ChatAnyscale(model_name="mistralai/Mixtral-8x7B-Instruct-v0.1")


# code adapted from Penn Mobile <3
def update_token():
    global token, expiration
    body = {
        "client_id": os.environ.get("DINING_ID"),
        "client_secret": os.environ.get("DINING_SECRET"),
        "grant_type": "client_credentials",
    }
    response = requests.post(OPENID_ENDPOINT, data=body).json()
    if "error" in response:
        raise Exception(response["Can't connect to Penn Dining (token)"])
    expiration = datetime.now() + timedelta(seconds=response["expires_in"])
    token = response["access_token"]


def request(*args, **kwargs):
    global token, expiration
    """Make a signed request to the dining API."""
    update_token()
    print(*args, kwargs)
    headers = {"Authorization": f"Bearer {token}"}

    # add authorization headers
    if "headers" in kwargs:
        kwargs["headers"].update(headers)
    else:
        kwargs["headers"] = headers

    try:
        return requests.request(*args, **kwargs)
    except:
        raise Exception("Can't connect to Penn Dining (request)")


# even more copied from penn mobile sorry
def get_venues():
    venues_route = OPEN_DATA_ENDPOINTS["VENUES"]
    response = request("GET", venues_route)
    if response.status_code != 200:
        raise Exception()
    venues = response.json()["result_data"]["campuses"]["203"]["cafes"]
    results = {key: value["name"] for key, value in venues.items()}
    return results


def get_menu(venue_id: str, date: datetime):
    menu_base = OPEN_DATA_ENDPOINTS["MENUS"]
    # get string of day/month/year
    date = date.strftime("%Y-%m-%d")
    response = request("GET", f"{menu_base}?cafe={venue_id}&date={date}")
    if response.status_code != 200:
        raise Exception()
    return response.json()


def update_menu(date: datetime):
    venues = get_venues()
    # venues = ['593', '636', '637', '638', '639', '641', '642', '747', '1057', '1163', '1442', '1732', '1733', '1464004', '1464009']
    skipped_venues = ["747", "1163", "1731", "1732", "1733", "1464004", "1464009"]
    results = dict()
    for venue, name in venues.items():
        if venue in skipped_venues:
            continue
        menu = get_menu(venue, date)
        sleep(1)
        results[name] = menu
    return results


sg = sendgrid.SendGridAPIClient(api_key=os.environ.get("SENDGRID_API_KEY"))


def send_email(content: str, to: str):
    from_email = Email("updates@penndiningalert.com")
    to_email = To(to)
    subject = "Your Daily Dining Update"
    content = Content("text/plain", content)
    mail = Mail(from_email, to_email, subject, content)
    mail_json = mail.get()
    return sg.client.mail.send.post(request_body=mail_json)


def notify_users(menu, users):
    for user in users:
        content = ""
        print(users)
        preferences = user["preferences"]
        prompt = f"""
        You are an intelligent expert on dining halls within UPenn. UPenn dining halls are known for their mixed quality and high variance, so it is important to know what is being served at each dining hall and to take food descriptions with a grain of salt.
        
        Your job is to read the user's dining preferences, as well as the dinner menus for each dining hall today. Then, you will generate a list of dining halls and highlights of the menu items that the user would be interested in. Keep in mind the user's preferences, and be realistic about the dining hall's quality. Try to focus on featured entrees and other substantive items, returning a maximum of five per dining hall and avoiding duplicates.
        
        Here are the user's preferences:
        {preferences}
        
        Here are the dinner menus for each dining hall today, presented in a dictionary format. Note that some dining halls may not have a dinner menu today:
        
        {menu}
        
        ---
        
        Please give solely the list of dining halls and food in a JSON format.
        """
        messages = [
            SystemMessage(
                content="You are a helpful AI. Please provide what is asked for in the prompt without any additional information or small talk."
            ),
            HumanMessage(
                content=prompt,
            ),
        ]

        response = llm(
            messages,
            response_format={
                "type": "json_object",
                "schema": {
                    "type": "object",
                    "properties": {
                        "dining_halls": {
                            "type": "array",
                            "items": {
                                "type": "object",
                                "properties": {
                                    "name": {"type": "string"},
                                    "menu_items": {
                                        "type": "array",
                                        "items": {"type": "string"},
                                    },
                                },
                                "required": ["name", "menu_items"],
                            },
                        }
                    },
                    "required": ["dining_halls"],
                },
            },
        )
        print(response.content)
        print(type(response.content))
        results = json.loads(response.content)
        formatted_response = ""
        for dining_hall in results["dining_halls"]:
            if len(dining_hall["menu_items"]) == 0:
                continue
            formatted_response += f"{dining_hall['name']}: {', '.join(dining_hall['menu_items'])}\n"
        if len(formatted_response) == 0:
            content = "No items found for your preferences today."
        else:
            content = f"""
            Hello! Here are some highlights today for dinner options on campus.
            {formatted_response}
            """

        send_email(content, user["email"])
