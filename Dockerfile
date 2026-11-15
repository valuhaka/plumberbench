# The online play server (plumberbench.org/play/), run as a Cloudflare Container
# behind the site's Worker. Any host that runs a Linux container on port 8080 works.
FROM python:3.13-slim

# Headless OpenGL through EGL (Mesa, CPU only) and a font for the tags.
RUN apt-get update && apt-get install -y --no-install-recommends \
        libegl1 libegl-mesa0 libgl1 libgl1-mesa-dri libgbm1 libglvnd0 fonts-dejavu-core \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /app
COPY pyproject.toml README.md LICENSE ./
COPY src ./src
RUN pip install --no-cache-dir .

ENV MUJOCO_GL=egl PYTHONUNBUFFERED=1
EXPOSE 8080
CMD ["python", "-m", "plumberbench.online", "--port", "8080"]
