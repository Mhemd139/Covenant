FROM python:3.12-slim
WORKDIR /app
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt
COPY test_mcp_server/ ./test_mcp_server/
EXPOSE 8000
CMD ["python", "-m", "test_mcp_server.server"]
