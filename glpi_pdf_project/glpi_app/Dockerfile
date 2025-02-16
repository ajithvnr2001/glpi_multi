FROM python:3.11-slim

ENV DEBIAN_FRONTEND=noninteractive
ENV PYTHONUNBUFFERED=1
# Set NLTK_DATA *before* installing any packages that might use nltk
ENV NLTK_DATA=/usr/local/share/nltk_data

WORKDIR /app

COPY requirements.txt /app/
RUN pip install --no-cache-dir -r requirements.txt

# Download ALL required NLTK data during build, to a standard location
RUN python -m nltk.downloader -d /usr/local/share/nltk_data punkt averaged_perceptron_tagger maxent_ne_chunker words

COPY . /app/

EXPOSE 8001

# Use Gunicorn for production
CMD ["gunicorn", "main:app", "-w", "4", "-k", "uvicorn.workers.UvicornWorker", "--bind", "0.0.0.0:8001"]
