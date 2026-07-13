FROM python:3.12-slim AS builder

WORKDIR /app

ENV PATH=/root/.local/bin:$PATH
RUN pip install pipx && \
    pipx ensurepath && \
    pipx install poetry
RUN apt update && apt install -y git nodejs npm

COPY . .

# 构建前端产物
RUN cd javsp/webapp/frontend && npm install && npm run build

RUN poetry self add poetry-dynamic-versioning && \
    poetry config virtualenvs.in-project true && \
    poetry install && \
    rm -rf /app/.git


FROM python:3.12-slim as runner

WORKDIR /app

COPY --from=builder /app/ /app/

ENV JAVSP_HOST=0.0.0.0
ENV JAVSP_PORT=5001
EXPOSE 5001

ENTRYPOINT ["/app/.venv/bin/python", "-m", "javsp.webapp.server"]
CMD ["--host", "0.0.0.0", "--port", "5001"]
