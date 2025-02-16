import requests
import json
from typing import List, Dict, Optional
import logging
from tenacity import retry, stop_after_attempt, wait_exponential
import os

# Configure logging
logger = logging.getLogger(__name__)

class GLPIConnector:
    """Connects to the GLPI API and performs actions like session management and ticket retrieval."""

    def __init__(self, glpi_url: str, app_token: str, user_token: Optional[str] = None, max_retries: int = 3):
        """Initializes the GLPIConnector.

        Args:
            glpi_url: Base URL of your GLPI instance's API (e.g., .../apirest.php).
            app_token: GLPI App Token.
            user_token: GLPI User Token (optional).
            max_retries: Maximum number of retries for API calls.
        """
        self.glpi_url = glpi_url
        self.app_token = app_token
        self.headers = {
            "Content-Type": "application/json",
            "App-Token": self.app_token,
        }
        self.session_token = None
        self.user_token = user_token
        self.max_retries = max_retries

    @retry(stop=stop_after_attempt(3), wait=wait_exponential(multiplier=1, min=1, max=5))
    def init_session(self) -> bool:
        """Initializes a GLPI session and gets the session token.

        Returns:
            True if the session was initialized successfully, False otherwise.
        """
        init_url = f"{self.glpi_url}/initSession"
        if self.user_token:
            self.headers["Authorization"] = f"user_token {self.user_token}"
        try:
            response = requests.get(init_url, headers=self.headers)
            response.raise_for_status()  # Raise HTTPError for bad responses (4xx or 5xx)
            self.session_token = response.json().get("session_token")
            if self.session_token:
                self.headers["Session-Token"] = self.session_token
                if "Authorization" in self.headers:
                    del self.headers["Authorization"]
                logger.info("GLPI session initialized successfully.")
                return True
            else:
                logger.error("Error: Could not initialize GLPI session.")
                return False
        except requests.exceptions.RequestException as e:
            logger.error(f"Error initializing session: {e}", exc_info=True)
            return False

    @retry(stop=stop_after_attempt(3), wait=wait_exponential(multiplier=1, min=1, max=5))
    def kill_session(self) -> bool:
        """Kills the current GLPI session.

        Returns:
            True if the session was killed successfully, False otherwise.
        """
        kill_url = f"{self.glpi_url}/killSession"

        if not self.session_token:
            return True

        try:
            response = requests.get(kill_url, headers=self.headers)
            response.raise_for_status()
            logger.info("GLPI session killed successfully.")
            return True
        except requests.exceptions.RequestException as e:
            logger.error(f"Error killing session: {e}", exc_info=True)
            return False


    @retry(stop=stop_after_attempt(3), wait=wait_exponential(multiplier=1, min=1, max=5))
    def get_tickets(self, range_str: str = "0-10") -> List[Dict]:
        """Retrieves a list of tickets from GLPI. Not used in current flow."""
        logger.warning("get_tickets is not used in the current implementation.")
        return []


    @retry(stop=stop_after_attempt(3), wait=wait_exponential(multiplier=1, min=1, max=5))
    def get_ticket(self, ticket_id: int) -> Optional[Dict]:
        """Retrieves a single ticket from GLPI, including document info."""
        if not self.session_token:
            if not self.init_session():
                return None

        ticket_url = f"{self.glpi_url}/Ticket/{ticket_id}"

        try:
            response = requests.get(ticket_url, headers=self.headers)
            response.raise_for_status()
            ticket = response.json()
            logger.info(f"Retrieved ticket {ticket_id}.")

            # Fetch associated documents
            documents = self.get_ticket_documents(ticket_id)
            ticket['documents'] = documents
            return ticket

        except requests.exceptions.RequestException as e:
            logger.error(f"Error retrieving ticket {ticket_id}: {e}", exc_info=True)
            return None

    @retry(stop=stop_after_attempt(3), wait=wait_exponential(multiplier=1, min=1, max=5))
    def get_ticket_documents(self, ticket_id: int) -> List[Dict]:
        """Retrieves document information associated with a ticket."""
        if not self.session_token:
            if not self.init_session():
                return []

        # Get linked items (which can include Documents)
        linked_items_url = f"{self.glpi_url}/Ticket/{ticket_id}/Item_Ticket"
        try:
            response = requests.get(linked_items_url, headers=self.headers)
            response.raise_for_status()
            linked_items = response.json()
            logger.info(f"Retrieved linked items for ticket {ticket_id}.")

            documents = []
            for item in linked_items:
                if item.get('itemtype') == 'Document':
                    # Fetch document details
                    document_url = f"{self.glpi_url}/Document/{item.get('items_id')}?expand_dropdowns=true"
                    doc_response = requests.get(document_url, headers=self.headers)
                    doc_response.raise_for_status()
                    doc_data = doc_response.json()

                    # Construct the download URL
                    download_url = f"{self.glpi_url}/Document/{item.get('items_id')}"
                    # Get the filename
                    filename = doc_data.get('filename')
                    if filename:
                        documents.append({
                            "id": item.get("items_id"),
                            "filename": filename,
                            "download_url": download_url,
                            "filepath": os.path.join,
                        })
                        logger.info(f"Found document {filename} for ticket {ticket_id}.")

            return documents

        except requests.exceptions.RequestException as e:
            logger.error(f"Error retrieving documents for ticket {ticket_id}: {e}", exc_info=True)
            return []
