# Snapdeal Virtual KAM

## Run locally
```
pip install -r requirements.txt
cp .env.example .env      # put your Gemini key in .env
cd backend
python -m uvicorn main:app --port 8000
```
Open http://localhost:8000 in Chrome, use headphones, click Start call, allow the mic.
Use localhost or HTTPS, because browsers block the mic on plain http.

## Test
```
python -m pytest tests -q
python eval/run_eval.py     # needs GEMINI_API_KEY, runs 6 personas
```

## Deploy (Render)
New Web Service from the repo. Build: `pip install -r requirements.txt`.
Start: `cd backend && uvicorn main:app --host 0.0.0.0 --port $PORT`.
Add GEMINI_API_KEY as an environment variable (never commit .env).

## Layout
backend/ (main.py API, agent.py Gemini loop, tools.py tools, prompts.py, data/seller.json), frontend/ (page, voice pipeline), eval/, tests/, NOTE.md
