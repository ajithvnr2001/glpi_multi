import os
from fastapi import FastAPI, Request, BackgroundTasks
from glpi_connector import GLPIConnector
from llm_service import LLMService
from pdf_generator import PDFGenerator
from dotenv import load_dotenv
from typing import Dict, Any, List, Optional
import uvicorn
import json
import re
import yaml
import logging
import requests

# Configure logging
logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(name)s - %(levelname)s - %(message)s')
logger = logging.getLogger(__name__)

load_dotenv()

app = FastAPI()

# Load configuration from YAML file
try:
    with open("config.yaml", "r") as f:
        config = yaml.safe_load(f)
        DEFAULT_PROMPT = config.get('prompt', "Summarize this GLPI ticket:")
        DEFAULT_IMAGE_PROMPT = config.get('image_prompt', "Describe this image and its relevance to a help desk ticket:")
except FileNotFoundError:
    logger.warning("config.yaml not found, using default prompt.")
    DEFAULT_PROMPT = "Summarize this GLPI ticket:"
    DEFAULT_IMAGE_PROMPT = "Describe this image and its relevance to a help desk ticket:"
except Exception as e:
    logger.error(f"Error loading config.yaml: {e}", exc_info=True)
    DEFAULT_PROMPT = "Summarize this GLPI ticket:"
    DEFAULT_IMAGE_PROMPT = "Describe this image and its relevance to a help desk ticket:"

class AutoPDF:
    def __init__(self):
        self.glpi_url = os.getenv("GLPI_URL")
        self.app_token = os.getenv("GLPI_APP_TOKEN")
        self.user_token = os.getenv("GLPI_USER_TOKEN")
        self.max_retries = int(os.getenv("MAX_RETRIES", 3))
        self.glpi = GLPIConnector(self.glpi_url, self.app_token, self.user_token, self.max_retries)
        self.llm_service = LLMService()
        self.text_prompt_template = os.getenv("PROMPT", DEFAULT_PROMPT)
        self.image_prompt_template = os.getenv("IMAGE_PROMPT", DEFAULT_IMAGE_PROMPT)

    async def process_ticket(self, ticket_id: int):
        try:
            ticket = self.glpi.get_ticket(ticket_id)
            if not ticket:
                logger.error(f"Could not retrieve ticket {ticket_id}")
                return

            text_summary = ""
            image_summary = ""

            if ticket.get('content'):
                text_query = self.text_prompt_template.format(ticket_content=ticket.get('content', ''))
                text_summary = self.llm_service.rag_completion([ticket], text_query)

            temp_image_paths = []
            for doc in ticket.get('documents', []):
                image_path = await self.download_image(doc["download_url"], doc["filename"])
                if image_path:
                    temp_image_paths.append(image_path)
                    image_result = self.llm_service.process_image(image_path, self.image_prompt_template)
                    if image_result:
                        image_summary += image_result + "\n"

            final_result = self.combine_summaries(text_summary, image_summary)
            cleaned_result = self.post_process_llm_output(final_result)

            pdf_generator = PDFGenerator(f"glpi_ticket_{ticket_id}.pdf")
            pdf_generator.generate_report(
                f"Ticket Analysis - #{ticket_id}",
                cleaned_result,
                [{"source_id": ticket_id, "source_type": "glpi_ticket"}]
            )

            for image_path in temp_image_paths:
                try:
                    os.remove(image_path)
                except OSError as e:
                    logger.error(f"Error deleting image {image_path}: {e}")

        except Exception as e:
            logger.error(f"Error processing ticket {ticket_id}: {e}")
        finally:
            self.glpi.kill_session()

    def combine_summaries(self, text_summary: str, image_summary: str) -> str:
        if text_summary and image_summary:
            return self.llm_service.complete(
                f"Combine these summaries:\nText: {text_summary}\nImages: {image_summary}"
            )
        return text_summary or image_summary or "No information available."

    async def download_image(self, download_url: str, filename: str) -> Optional[str]:
        try:
            response = requests.get(download_url, headers={
                "Session-Token": self.glpi.session_token,
                "App-Token": self.glpi.app_token
            }, stream=True)
            response.raise_for_status()

            safe_filename = re.sub(r'[\\/*?:"<>|]', "", filename)
            temp_dir = "temp_images"
            os.makedirs(temp_dir, exist_ok=True)

            file_extension = os.path.splitext(safe_filename)[1] or ".jpg"
            temp_file_path = os.path.join(temp_dir, f"{safe_filename}{file_extension}")

            with open(temp_file_path, "wb") as f:
                for chunk in response.iter_content(chunk_size=8192):
                    f.write(chunk)
            return temp_file_path
        except Exception as e:
            logger.error(f"Error downloading image: {e}")
            return None

    def post_process_llm_output(self, text: str) -> str:
        text = re.sub(r"Please let me know if you need any further assistance\.?|I'm here to help\.?|Best regards, \[Your Name] IT Support Assistant\.?", "", text, flags=re.IGNORECASE)
        lines = [line.strip() for line in text.split("\n") if line.strip()]
        text = "\n".join(lines)

        # Remove repetitive "Key Information" lines
        parts = text.split("Key Information:")
        if len(parts) > 1:
            text = "Key Information:".join(parts[:2])  # Keep only the first occurrence

        return text

auto_pdf_app = AutoPDF()

@app.post("/webhook")
async def glpi_webhook(request: Request, background_tasks: BackgroundTasks):
    try:
        data = await request.json()
        for event in data:
            if event.get("event") in ["add", "update"] and event.get("itemtype") == "Ticket":
                ticket_id = int(event.get("items_id"))
                background_tasks.add_task(auto_pdf_app.process_ticket, ticket_id)
                return {"message": f"Processing ticket {ticket_id}"}
        return {"message": "No relevant events found"}
    except Exception as e:
        return {"error": str(e)}

@app.get("/health")
async def health_check():
    return {"status": "OK"}

if __name__ == "__main__":
    uvicorn.run(app, host="0.0.0.0", port=8001, reload=True)
