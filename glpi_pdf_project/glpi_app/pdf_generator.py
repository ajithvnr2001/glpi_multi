import os
from reportlab.lib.pagesizes import letter
from reportlab.platypus import SimpleDocTemplate, Paragraph, Spacer, ListFlowable
from reportlab.lib.styles import ParagraphStyle
from reportlab.lib.units import inch
from reportlab.lib.enums import TA_LEFT, TA_CENTER
import boto3
from botocore.exceptions import ClientError
from typing import List, Dict
from datetime import datetime
from tenacity import retry, stop_after_attempt, wait_exponential

# --- Define Styles ---
_styles = {}

_styles['Heading1'] = ParagraphStyle(
    name='Heading1',
    fontSize=16,
    spaceAfter=12,
    alignment=TA_CENTER,
)
_styles['Heading2'] = ParagraphStyle(
    name='Heading2',
    fontSize=14,
    spaceBefore=10,
    spaceAfter=6,
)
_styles['Normal_C'] = ParagraphStyle(
    name='Normal_C',
    alignment=TA_CENTER,
    spaceAfter=6,
)
_styles['Bullet'] = ParagraphStyle(
    name='Bullet',
    fontSize=11,
    leftIndent=30,
    spaceBefore=3,
)
_styles['Normal'] = ParagraphStyle(
    name='Normal',
    fontSize=11,
    spaceAfter=6,
)

class PDFGenerator:
    """Generates PDF reports using ReportLab and uploads them to Wasabi S3."""

    def __init__(self, filename: str):
        self.filename = filename
        self.doc = SimpleDocTemplate(self.filename, pagesize=letter)
        self.styles = _styles

        # Wasabi S3 Configuration
        self.s3_client = boto3.client(
            's3',
            endpoint_url=os.environ.get("WASABI_ENDPOINT_URL"),
            aws_access_key_id=os.environ.get("WASABI_ACCESS_KEY_ID"),
            aws_secret_access_key=os.environ.get("WASABI_SECRET_ACCESS_KEY"),
            region_name=os.environ.get("WASABI_REGION")
        )
        self.bucket_name = os.environ.get("WASABI_BUCKET_NAME")
        if not all([self.bucket_name, self.s3_client]):
            raise ValueError("Wasabi S3 environment variables not set.")

    def generate_report(self, title: str, result: str, source_info: List[Dict]):
        elements = []
        elements.append(Paragraph(title, self.styles['Heading1']))
        elements.append(Spacer(1, 0.2 * inch))
        elements.append(Paragraph("Result:", self.styles['Heading2']))
        elements.append(Spacer(1, 0.1 * inch))
        self._add_structured_result(elements, result)
        elements.append(Spacer(1, 0.2 * inch))

        elements.append(Paragraph("Source Information:", self.styles['Heading2']))
        elements.append(Spacer(1, 0.1 * inch))
        for source in source_info:
            elements.append(Paragraph(f"Source ID: {source.get('source_id', 'N/A')}", self.styles['Normal']))
            elements.append(Paragraph(f"Source Type: glpi_ticket", self.styles['Normal']))
            break

        self.doc.title = title
        self.doc.author = "AutoPDF (GLPI Ticket Summarizer)"
        self.doc.subject = "GLPI Ticket Summary"
        self.doc.keywords = ["GLPI", "Ticket", "Summary", "PDF"]
        self.doc.creator = "AutoPDF"

        try:
            self.doc.build(elements)
            self.upload_to_s3(self.filename)
        except ClientError as e:
            print(f"S3 Upload Error: {e}")
        except Exception as e:
            print(f"Error generating or uploading PDF: {e}")
        finally:
            if os.path.exists(self.filename):
                os.remove(self.filename)

    @retry(stop=stop_after_attempt(3), wait=wait_exponential(multiplier=1, min=1, max=5))
    def upload_to_s3(self, filename: str):
        try:
            self.s3_client.upload_file(filename, self.bucket_name, filename)
        except ClientError as e:
            raise

    def _add_structured_result(self, elements, result_text):
        sections = result_text.split("**")
        for i in range(1, len(sections), 2):
            title = sections[i].strip()
            content = sections[i+1].strip() if i + 1 < len(sections) else ""

            elements.append(Paragraph(title, self.styles['Heading2']))
            if title in ["Troubleshooting Steps:", "Solution:"]:
                items = [item.strip() for item in content.split("*") if item.strip()]
                list_flowable = ListFlowable(
                    [Paragraph(item, self.styles['Bullet']) for item in items],
                    bulletType='bullet'
                )
                elements.append(list_flowable)
            else:
                elements.append(Paragraph(content, self.styles['Normal']))
