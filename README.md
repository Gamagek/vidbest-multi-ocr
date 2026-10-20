# Vid.Best Multi-OCR

Experimental low-memory video frame OCR worker for Portainer (AMD64). See docker-compose.yml and worker.py. Does not modify Vid.Best D1 or publish reviews.

**Security:** Set GEMINI_API_KEY through Portainer environment variables, never commit it. Gemini model names are checked against the API model catalog before requests. The service requires locally mounted input video files and Docker build support.
