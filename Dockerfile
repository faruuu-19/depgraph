FROM python:3.11-slim

WORKDIR /app
COPY pyproject.toml README.md ./
COPY src ./src

RUN pip install --no-cache-dir .

ENV MCP_TRANSPORT=http
EXPOSE 8000

CMD ["dep-graph-guard"]
