# Aurai knowledge service image. Contains the service, the ingestion CLI and the synthetic demo corpus.
# In AWS, ingestion reads from S3 and the baked-in corpus is simply unused.
FROM python:3.13-slim AS build
WORKDIR /build
COPY pyproject.toml README.md ./
COPY src ./src
RUN pip install --no-cache-dir --prefix=/install ".[s3]"

FROM python:3.13-slim
COPY --from=build /install /usr/local
COPY corpus /corpus
RUN useradd --uid 10001 --no-create-home --shell /usr/sbin/nologin aurai
USER 10001
EXPOSE 8000
ENV PYTHONUNBUFFERED=1
ENTRYPOINT ["aurai-knowledge"]
CMD ["serve", "--port", "8000"]

LABEL org.opencontainers.image.title="aurai-knowledge" \
      org.opencontainers.image.description="Aurai knowledge service: entitlement-aware retrieval" \
      org.opencontainers.image.licenses="MIT"
