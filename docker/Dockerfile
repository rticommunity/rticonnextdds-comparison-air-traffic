# ── ATC Demo with RTI Connext DDS ────────────────────────────────────────────
#
# Build (from repo root):
#   docker build -f docker/Dockerfile -t atc-demo .
#
# Run the DDS implementation (all processes):
#
#   Linux (--network host enables DDS multicast discovery across containers):
#     docker run --rm --env-file .env.local -v ./rti_license.dat:/tmp/rti_license.dat --network host atc-demo dds
#
#   macOS (Docker Desktop runs in a VM; use -p to forward the dashboard port):
#     docker run --rm --env-file .env.local -v ./rti_license.dat:/tmp/rti_license.dat -p 8050:8050 atc-demo dds
#
#   Windows (same as macOS — Docker Desktop uses a VM):
#     docker run --rm --env-file .env.local -v ./rti_license.dat:/tmp/rti_license.dat -p 8050:8050 atc-demo dds
#
# Run the gRPC implementation (no RTI license required):
#   docker run --rm --env-file .env.local -p 8050:8050 atc-demo grpc
#
# Run a single component (append the implementation and component names):
#   docker run --rm --env-file .env.local -v ./rti_license.dat:/tmp/rti_license.dat -p 8050:8050 atc-demo dds dashboard
#   docker run --rm --env-file .env.local -p 8050:8050 atc-demo grpc dashboard
#
# Components: all (default), dashboard, center, tower, tracon, airport,
#             airplane, flightplan, weather

FROM python:3.14-slim

# Prevent Python from writing .pyc files and buffering stdout/stderr
ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1

WORKDIR /app

# Install dependencies first (layer caching)
COPY requirements/connext_dds.txt requirements/grpc.txt requirements/
RUN pip install --no-cache-dir \
    -r requirements/connext_dds.txt \
    -r requirements/grpc.txt

# Copy only files required at runtime
COPY connext_dds/python/*.py connext_dds/python/
COPY connext_dds/scripts/demo_cli.py connext_dds/scripts/demo_start.sh connext_dds/scripts/
COPY connext_dds/air_traffic_qos.xml connext_dds/
COPY grpc/python/*.py grpc/python/
COPY grpc/scripts/demo_cli.py grpc/scripts/demo_start.sh grpc/scripts/
COPY docker/docker-entrypoint.sh .
COPY air_traffic_scenario.json LICENSE ./

# Dashboard port
EXPOSE 8050

ENTRYPOINT ["/app/docker-entrypoint.sh"]
CMD ["all"]
