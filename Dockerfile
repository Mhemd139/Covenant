# Covenant: proxy + operator in one image; give the full command per role.
#   proxy:    docker run covenant-mcp covenant proxy --upstream http://... --host 0.0.0.0
#   operator: docker run covenant-mcp kopf run -m covenant.operator.handlers --all-namespaces
FROM python:3.12-slim

WORKDIR /app
COPY pyproject.toml README.md ./
COPY covenant ./covenant
RUN pip install --no-cache-dir ".[proxy,operator]"

RUN useradd --create-home --uid 1000 covenant
USER covenant

CMD ["covenant", "--help"]
