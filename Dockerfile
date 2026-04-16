FROM python:3.12-alpine

RUN apk add --no-cache \
    bash \
    openssh-client \
    mosh \
    tmux \
    fzf \
    jq \
    iputils \
    procps \
    bc

WORKDIR /app

COPY pyproject.toml requirements.txt ./
COPY hermes_gate/ ./hermes_gate/

RUN pip install --no-cache-dir -e .

COPY entrypoint.sh .
RUN chmod +x entrypoint.sh

ENTRYPOINT ["./entrypoint.sh"]
