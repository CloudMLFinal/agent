FROM python:3.11-slim

LABEL version="1.0.0"
LABEL description="Log Repair Agent"
LABEL maintainer="Kamiku Xue | Ning Miao | Raymond Lu"

# Create a non-root user
RUN useradd -m app
USER app

# Set the working directory
WORKDIR /app
COPY . /app/

# Install dependencies
RUN pip install --no-cache-dir -r requirements.txt


# Run the application
CMD ["python", "main.py"]