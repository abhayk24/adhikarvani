# AdhikarVani: runs on Render (free web service) or a Hugging Face Docker Space
FROM python:3.11-slim

ENV PYTHONDONTWRITEBYTECODE=1 PYTHONUNBUFFERED=1 PIP_NO_CACHE_DIR=1 PIP_DISABLE_PIP_VERSION_CHECK=1

# ffmpeg: normalises browser recordings. Tesseract + Indic language packs: OCR for scanned
# and legacy-font PDFs (OSD script detection picks the right pack automatically).
RUN apt-get update && apt-get install -y --no-install-recommends \
        ffmpeg tesseract-ocr tesseract-ocr-hin tesseract-ocr-ben tesseract-ocr-tam tesseract-ocr-tel \
        tesseract-ocr-mar tesseract-ocr-guj tesseract-ocr-kan tesseract-ocr-mal tesseract-ocr-pan \
        tesseract-ocr-ori tesseract-ocr-urd \
    && rm -rf /var/lib/apt/lists/*

# Spaces run containers as uid 1000
RUN useradd -m -u 1000 user
USER user
ENV HOME=/home/user PATH=/home/user/.local/bin:$PATH
WORKDIR /home/user/app

COPY --chown=user requirements.txt .
RUN pip install --user -r requirements.txt

COPY --chown=user . .

ENV PORT=7860
EXPOSE 7860
# One worker on purpose: live compile jobs are tracked in memory. $PORT is set by Render (HF uses 7860).
CMD ["sh", "-c", "exec uvicorn app.main:app --host 0.0.0.0 --port ${PORT:-7860} --proxy-headers --forwarded-allow-ips '*'"]
