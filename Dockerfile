# Use the official Python slim image from the Docker Hub
FROM python:3.9-slim

# Set the working directory in the container
WORKDIR /app

# Install ffmpeg and clean up apt cache
RUN apt-get update && apt-get install -y ffmpeg sqlite3 && apt-get clean && rm -rf /var/lib/apt/lists/*

# Copy requirements.txt into the container
COPY requirements.txt /app/requirements.txt

# Install any needed packages specified in requirements.txt
RUN pip install --no-cache-dir -r requirements.txt

# Copy the current directory contents into the container at /app
COPY . /app

# Create a directory for SQLite database
RUN mkdir -p /app/data

# Make port 8000 available to the world outside this container
EXPOSE 8000

# Define environment variable
ENV NAME=FastAPI-TTS

# Run the Gunicorn server with Uvicorn workers
CMD ["gunicorn", "main:app", "-k", "uvicorn.workers.UvicornWorker", "--bind", "0.0.0.0:8000", "--workers", "9"]
