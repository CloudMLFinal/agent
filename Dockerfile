FROM python:3.11-alpine

LABEL version="1.0.0"
LABEL description="Log Repair Agent"
LABEL maintainer="Kamiku Xue | Ning Miao | Raymond Lu"

# system dependencies
RUN apk add --no-cache \
    build-base \
    libffi-dev \
    openssl-dev \
    git

# set git username and email
RUN git config --global user.name "Code Fix Agent"
RUN git config --global user.email "code-fix@agent.io"

# Create a non-root user
RUN addgroup -S app && adduser -S app -G app

# Set the working directory
WORKDIR /app
COPY . /app/

# Install dependencies
RUN pip install --no-cache-dir -r requirements.txt

# Run the application
CMD ["python", "main.py"]