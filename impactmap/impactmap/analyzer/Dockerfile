FROM python:3.12-slim

# git is required at runtime for the "Diff impact" tab (subprocess: git diff --name-only)
RUN apt-get update \
 && apt-get install -y --no-install-recommends git \
 && rm -rf /var/lib/apt/lists/*

WORKDIR /app
COPY requirements.txt .
RUN pip install -r requirements.txt
COPY . .
CMD ["streamlit", "run", "dashboard.py", "--server.address", "0.0.0.0", "--server.port", "8501"]
