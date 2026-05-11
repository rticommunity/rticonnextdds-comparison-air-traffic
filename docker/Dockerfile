# ── ATC Demo with RTI Connext DDS ────────────────────────────────────────────
#
# Build (from repo root):
#   docker build -f docker/Dockerfile -t atc-demo .
#
# Run (all processes):
#
#   Linux (--network host enables DDS multicast discovery across containers):
#     docker run --rm -v ./rti_license.dat:/tmp/rti_license.dat --network host atc-demo
#
#   macOS (Docker Desktop runs in a VM; use -p to forward the dashboard port):
#     docker run --rm -v ./rti_license.dat:/tmp/rti_license.dat -p 8050:8050 atc-demo
#
#   Windows (same as macOS — Docker Desktop uses a VM):
#     docker run --rm -v ./rti_license.dat:/tmp/rti_license.dat -p 8050:8050 atc-demo
#
# Run a single component (append the component name):
#   docker run --rm -v ./rti_license.dat:/tmp/rti_license.dat -p 8050:8050 atc-demo dashboard
#
# Components: all (default), dashboard, center, tower, tracon, airport,
#             airplane, flightplan, weather

FROM python:3.14-slim

# Prevent Python from writing .pyc files and buffering stdout/stderr
ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1

WORKDIR /app

# Install dependencies first (layer caching)
COPY requirements/ requirements/
RUN pip install --no-cache-dir -r requirements/connext_dds.txt

# Copy project files
COPY connext_dds/python/ connext_dds/python/
COPY connext_dds/scripts/ connext_dds/scripts/
COPY connext_dds/air_traffic_qos.xml connext_dds/air_traffic_scenario.json connext_dds/
COPY docker/docker-entrypoint.sh .

# Dashboard port
EXPOSE 8050

ENTRYPOINT ["/app/docker-entrypoint.sh"]
CMD ["all"]
