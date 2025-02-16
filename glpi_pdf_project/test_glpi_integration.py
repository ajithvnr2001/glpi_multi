import requests
import json
from typing import Optional, Dict

# HARDCODED CREDENTIALS - FOR TESTING ONLY.  DO NOT USE IN PRODUCTION.
GLPI_URL = "https://ltimindtree.in1.glpi-network.cloud/apirest.php"
GLPI_APP_TOKEN = "your_glpi_app_token"  # Replace
GLPI_USER_TOKEN = "your_glpi_user_token"  # Replace
WEBHOOK_URL = "http://localhost:8001/webhook"  # Or your Docker host IP

def create_glpi_ticket(glpi_url, app_token, user_token, ticket_data: dict) -> Optional[int]:
    init_headers = {
        "Content-Type": "application/json",
        "App-Token": app_token,
    }
    if user_token:
        init_headers["Authorization"] = f"user_token {user_token}"

    init_url = f"{glpi_url}/initSession"
    try:
        response = requests.get(init_url, headers=init_headers)
        response.raise_for_status()
        session_token = response.json().get("session_token")
    except requests.exceptions.RequestException as e:
        print(f"Error initializing GLPI session: {e}")
        return None

    if not session_token:
        print("Error: Could not obtain GLPI session token.")
        return None

    ticket_url = f"{glpi_url}/Ticket/"
    headers = {
        "Content-Type": "application/json",
        "Session-Token": session_token,
        "App-Token": app_token,
    }
    payload = {"input": ticket_data}

    try:
        response = requests.post(ticket_url, headers=headers, json=payload)
        response.raise_for_status()
        new_ticket_id = response.json().get("id")
        print(f"Ticket created successfully!  ID: {new_ticket_id}")
        return new_ticket_id
    except requests.exceptions.RequestException as e:
        print(f"Error creating GLPI ticket: {e}")
        return None
    finally:
        kill_url = f"{glpi_url}/killSession"
        try:
            requests.get(kill_url, headers=headers)
        except requests.exceptions.RequestException as e:
            print(f"Error killing session: {e}")

def send_glpi_webhook(webhook_url: str, ticket_id: int):
    headers = {"Content-Type": "application/json"}
    data = [
        {
            "event": "add",
            "itemtype": "Ticket",
            "items_id": str(ticket_id),
        }
    ]

    try:
        response = requests.post(webhook_url, headers=headers, data=json.dumps(data))
        response.raise_for_status()
        print(f"Webhook sent successfully! Response: {response.json()}")
    except requests.exceptions.RequestException as e:
        print(f"Error sending webhook: {e}")

if __name__ == "__main__":
    ticket_data = {
        "name": "Network Outage - Building B - CRITICAL - with Image",
        "content": """
            All users in Building B are reporting a complete network outage.
            No internet access, no internal network access.  This is a critical
            issue affecting all departments in the building.  The outage began
            around 1:00 PM on February 16, 2025.

            Possible causes:
            * Power outage affecting network equipment.
            * Failure of the main switch for Building B.
            * Fiber cut or other connectivity issue to Building B.

            Troubleshooting steps taken:
            * Verified power to the main server room (Building A) - OK.
            * Attempted to ping the Building B switch - no response.
            * Checked upstream provider status - no reported outages.

            Solution:
            * Discovered a failed power supply in the Building B main switch.
            * Replaced the power supply.
            * Switch came back online, and network connectivity was restored to Building B.
        """,
        "status": 2,
        "priority": 5,
        "type": 1,
        "category": 5,
    }

    new_ticket_id = create_glpi_ticket(GLPI_URL, GLPI_APP_TOKEN, GLPI_USER_TOKEN, ticket_data)
    if new_ticket_id:
        send_glpi_webhook(WEBHOOK_URL, new_ticket_id)
    else:
        print("Ticket creation failed.  Cannot send webhook.")
