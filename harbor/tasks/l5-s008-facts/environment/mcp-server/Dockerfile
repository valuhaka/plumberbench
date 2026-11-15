FROM python:3.13-slim

# Headless OpenGL through EGL (Mesa, CPU only) and a font for the tags.
RUN apt-get update && apt-get install -y --no-install-recommends \
        libegl1 libegl-mesa0 libgl1 libgl1-mesa-dri libgbm1 libglvnd0 fonts-dejavu-core \
    && rm -rf /var/lib/apt/lists/*
RUN pip install --no-cache-dir mujoco==4.0.1 pillow==12.3.0 numpy==2.5.3 fastmcp==4.2.0

ENV MUJOCO_GL=egl PYTHONPATH=/app PYTHONUNBUFFERED=1
WORKDIR /app
COPY plumberbench /app/plumberbench
EXPOSE 8000
CMD ["python", "-m", "plumberbench.server"]
