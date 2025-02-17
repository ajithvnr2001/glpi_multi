FROM python:3.11-slim

ENV DEBIAN_FRONTEND=noninteractive
ENV PYTHONUNBUFFERED=1

WORKDIR /app

COPY requirements.txt /app/

# Download NLTK data during image build
RUN python -m nltk.downloader punkt averaged_perceptron_tagger -d /usr/local/share/nltk_data

RUN pip install --no-cache-dir -r requirements.txt

COPY . /app/

EXPOSE 8001

CMD ["gunicorn", "main:app", "-w", "4", "-k", "uvicorn.workers.UvicornWorker", "--bind", "0.0.0.0:8001"]
