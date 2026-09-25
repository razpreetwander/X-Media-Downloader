
Base Python Image
FROM python:3.11-slim
Install Tor, netcat and system utilities
RUN apt-get update && apt-get install -y 
tor 
netcat-openbsd 
curl 
&& rm -rf /var/lib/apt/lists/*
Configure Tor Control Port on 9051 for requesting NEWNYM (New IP signal)
RUN echo "ControlPort 9051" >> /etc/tor/torrc && 
echo "CookieAuthentication 0" >> /etc/tor/torrc
Set working directory
WORKDIR /app
Install Python dependencies
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt
Copy backend files
COPY . .
Expose Render default port
EXPOSE 10000
Start Tor service and Uvicorn FastAPI server
CMD service tor start && uvicorn main:app --host 0.0.0.0 --port 10000