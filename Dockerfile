FROM python:3.11-slim

WORKDIR /app

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY app.py rebuild_database.py download_images.py update_rankings.py ./
COPY templates/ ./templates/
COPY static/ ./static/

RUN groupadd -r breeduser && useradd -r -g breeduser breeduser
RUN chown -R breeduser:breeduser /app

USER breeduser

ENV DATABASE_URL=/data/dog_breeds.db
ENV STATIC_DIR=/data/static
ENV FLASK_ENV=production

VOLUME ["/data"]

EXPOSE 5000

CMD ["gunicorn", "--bind", "0.0.0.0:5000", "--workers", "2", "app:app"]
