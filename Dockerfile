# Start from a specific, multi-arch Python image on the 'trixie' base
FROM python:3.14-slim-trixie

# avoid interactive prompts during package install
ENV DEBIAN_FRONTEND=noninteractive

# Install TeX Live (full scheme), unzip, git and SSH client
RUN apt-get update && apt-get install -y \
    texlive-full \
    unzip \
    git \
    openssh-client \
    ca-certificates \
    --no-install-recommends \
    && rm -rf /var/lib/apt/lists/*

# Set up our application directory
WORKDIR /app

# Create the persistent projects directory
RUN mkdir -p /app/projects

# Copy the new requirements file
COPY requirements.txt .

# Install the Python requirements
RUN pip install --no-cache-dir -r requirements.txt

# Copy the backend and frontend files into the container
COPY app.py .
COPY dashboard.html .
COPY editor.html .

# Tell Docker what command to run when the container starts
# This starts the Gunicorn web server with 2 workers
CMD ["gunicorn", "--workers=2", "--bind=0.0.0.0:5000", "app:app"]

