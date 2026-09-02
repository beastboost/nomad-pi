FROM python:3.11-slim

WORKDIR /app

# ffmpeg/ffprobe are not optional for this image: probing, HLS, ABR, remux and
# subtitle conversion all shell out to them, and without them the container
# serves a library it cannot play. gcc/libffi are needed to build bcrypt and
# psutil wheels.
RUN apt-get update && \
    apt-get install -y --no-install-recommends gcc libffi-dev ffmpeg && \
    rm -rf /var/lib/apt/lists/*

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt requests

COPY . .

# Create data directory
RUN mkdir -p data

# A container has no NetworkManager, no systemd and no host to reboot, so the
# runtime guard refuses host-management routes rather than shelling out to
# binaries that are not there. Hardware acceleration is off by default because
# the image cannot know what the host exposes; override it at run time when
# passing through a device.
ENV NOMAD_RUNTIME_MODE=server \
    NOMAD_HW_ACCEL=off \
    PYTHONUNBUFFERED=1

EXPOSE 8000

# Health check
HEALTHCHECK --interval=30s --timeout=5s --retries=3 \
    CMD python -c "import urllib.request; urllib.request.urlopen('http://localhost:8000/api/system/status')" || exit 1

CMD ["python", "-m", "uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8000"]
