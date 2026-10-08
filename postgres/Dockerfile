# Keep the existing PostgreSQL major version and Alpine runtime for volume compatibility.
FROM postgres:16-alpine AS vector-build

ARG PGVECTOR_VERSION=0.8.2

RUN apk add --no-cache build-base git \
    && git clone --branch "v${PGVECTOR_VERSION}" --depth 1 \
        https://github.com/pgvector/pgvector.git /tmp/pgvector \
    && make -C /tmp/pgvector OPTFLAGS="" with_llvm=no \
    && make -C /tmp/pgvector install with_llvm=no

FROM postgres:16-alpine

COPY --from=vector-build /usr/local/lib/postgresql/vector.so /usr/local/lib/postgresql/vector.so
COPY --from=vector-build /usr/local/share/postgresql/extension/vector* /usr/local/share/postgresql/extension/
COPY --from=vector-build /tmp/pgvector/LICENSE /usr/local/share/doc/pgvector/LICENSE
