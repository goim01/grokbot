# Use a lightweight Python base image
FROM python:3.10-slim

# Set working directory
WORKDIR /app

# Copy requirements and install dependencies
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# Copy the grokbot package
COPY grokbot/ grokbot/

# Set PYTHONPATH to include /app
ENV PYTHONPATH=/app:$PYTHONPATH

# Set environment variable for unbuffered Python output
ENV PYTHONUNBUFFERED=1

# Debug: List directory structure to verify files
RUN ls -R /app

# Run the bot
CMD ["python", "grokbot/bot.py"]