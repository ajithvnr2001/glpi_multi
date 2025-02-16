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
import yaml  # Import the YAML library
import logging
import base64

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
        DEFAULT_IMAGE_PROMPT = config.get('image_prompt', "Describe this image and its relevance to a help desk ticket:")  # Added
except FileNotFoundError:
    logger.warning("config.yaml not found, using default prompt.")
    DEFAULT_PROMPT = "Summarize this GLPI ticket:"
    DEFAULT_IMAGE_PROMPT = "Describe this image and its relevance to a help desk ticket:"
except Exception as e:
    logger.error(f"Error loading config.yaml: {e}", exc_info=True)
    DEFAULT_PROMPT = "Summarize this GLPI ticket:"
    DEFAULT_IMAGE_PROMPT = "Describe this image and its relevance to a help desk ticket:"



class AutoPDF:
    """Main class for the AutoPDF application."""

    def __init__(self):
        """Initializes the AutoPDF application."""
        self.glpi_url = os.getenv("GLPI_URL")
        self.app_token = os.getenv("GLPI_APP_TOKEN")
        self.user_token = os.getenv("GLPI_USER_TOKEN")
        self.max_retries = int(os.getenv("MAX_RETRIES", 3))  # Default to 3 retries
        self.glpi = GLPIConnector(self.glpi_url, self.app_token, self.user_token, max_retries=self.max_retries)
        self.llm_service = LLMService()
        self.text_prompt_template = os.getenv("PROMPT", DEFAULT_PROMPT)
        self.image_prompt_template = os.getenv("IMAGE_PROMPT", DEFAULT_IMAGE_PROMPT) # Added

    async def process_ticket(self, ticket_id: int):
        """Fetches ticket details, processes with LLM (text/image), and generates PDF."""
        try:
            ticket = self.glpi.get_ticket(ticket_id)
            if not ticket:
                logger.error(f"Error: Could not retrieve ticket with ID {ticket_id}")
                return

            text_summary = ""
            image_summary = ""

            # --- Text Processing (Akash) ---
            if ticket.get('content'):
                text_query = self.text_prompt_template.format(ticket_content=ticket.get('content', ''))
                text_summary = self.llm_service.rag_completion([ticket], text_query)
                logger.info(f"Text Summary (Akash): {text_summary}")


            # --- Image Processing (OpenRouter) ---
            # temp_image_paths = []  # Store paths to temporary image files #removed
            if ticket.get('documents'): #check if there are any documents.
                for doc in ticket.get('documents', []):
                    # Removed downlaod image
                    # image_path = await self.download_image(doc["download_url"], doc["filename"]) #removed

                    if doc.get('encoded_content'): #check for the encoded content
                        # temp_image_paths.append(image_path) #removed
                        image_prompt = self.image_prompt_template  # Use the image prompt
                        image_result = self.llm_service.process_image(doc.get('encoded_content'), image_prompt) #pass encoded content
                        if image_result:
                            image_summary += image_result + "\n"  # Accumulate image summaries

            # --- Combine Summaries ---
            if text_summary and image_summary:
                combined_prompt = f"""
Combine the following text summary and image summary into a single, coherent summary:

**Text Summary:**
{text_summary}

**Image Summary:**
{image_summary}
                """
                final_result = self.llm_service.complete(prompt=combined_prompt)

            elif text_summary:
                final_result = text_summary
            elif image_summary:
                final_result = image_summary
            else:
                final_result = "No information available."

            logger.info(f"Final Result: {final_result}")

            # --- Post-Processing & PDF Generation ---
            cleaned_result = self.post_process_llm_output(final_result)
            pdf_generator = PDFGenerator(f"glpi_ticket_{ticket_id}.pdf")
            source_info = [{"source_id": ticket_id, "source_type": "glpi_ticket"}]
            pdf_generator.generate_report(
                f"Ticket Analysis - #{ticket_id}", cleaned_result, source_info  # Pass ONLY the result
            )
            logger.info(f"Report generated: glpi_ticket_{ticket_id}.pdf")

        except Exception as e:
            logger.error(f"Error processing ticket {ticket_id}: {e}", exc_info=True)

        finally:
            if not self.glpi.kill_session():
                logger.warning("Failed to kill GLPI session.")


    def post_process_llm_output(self, text: str) -> str:
        """Cleans up the LLM output."""
        text = re.sub(r"Please let me know if you need any further assistance\.?|I'm here to help\.?|Best regards, \[Your Name] IT Support Assistant\.?", "", text, flags=re.IGNORECASE)
        text = re.sub(r"If you have any further questions or need any additional assistance.*", "", text, flags=re.IGNORECASE)
        text = re.sub(r"However, it is assumed that a ticket ID exists in the actual GLPI ticket\..*I don't know\.", "", text, flags=re.IGNORECASE)
        text = re.sub(r"No ticket ID is provided in the given content.*Ticket ID:  \(Unknown\)", "", text, flags=re.IGNORECASE)
        text = re.sub(r"Note: The provided content does not include a ticket ID\..*I don't know", "", text, flags=re.IGNORECASE)
        lines = text.split("\n")
        cleaned_lines = []
        for line in lines:
            line = line.strip()
            if line.startswith("*") and len(line) > 1:
                cleaned_lines.append(line)
            elif not line.startswith("*") and line:
                cleaned_lines.append(line)

        return "\n".join(cleaned_lines)


# --- FastAPI Endpoints ---

auto_pdf_app = AutoPDF()  # Create an instance of the main application class

@app.post("/webhook")
async def glpi_webhook(request: Request, background_tasks: BackgroundTasks):
    """Handles incoming webhook requests from GLPI."""
    try:
        data: List[Dict[str, Any]] = await request.json()
        logger.info(f"Received webhook data: {data}")

        for event in data:
            if event.get("event") in  ["add", "update"] and event.get("itemtype") == "Ticket":
                ticket_id = int(event.get("items_id"))
                background_tasks.add_task(auto_pdf_app.process_ticket, ticket_id)
                return {"message": f"Ticket processing initiated for ID: {ticket_id}"}

        return {"message": "Webhook received, but no relevant event found."}

    except json.JSONDecodeError:
        return {"error": "Invalid JSON payload"}
    except Exception as e:
      return {"error":str(e)}

@app.get("/test_llm")
async def test_llm_endpoint():
    test_prompt = "what is the capital of Assyria"
    response = auto_pdf_app.llm_service.complete(prompt=test_prompt)
    return {"response":response}

@app.get("/health")
async def health_check():
    """Simple health check endpoint."""
    return {"status": "OK"}

if __name__ == "__main__":
    # For development, run with uvicorn directly.
    uvicorn.run(app, host="0.0.0.0", port=8001, reload=True)
