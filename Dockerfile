# Use a lightweight Python base image
FROM python:3.10-slim

# Set working directory
WORKDIR /app

# Copy requirements and install dependencies
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# Copy the bot code
COPY bot.py .

# Set environment variable for unbuffered Python output
ENV PYTHONUNBUFFERED=1

# Run the bot
CMD ["python", "bot.py"]