# Flight Route Planner

A complete flight route planner using A* algorithm with real-world constraints, displayed on a 3D CesiumJS globe.

## Features
- Validated against real flights
- Takes restricted zones into account
- Simulates wind effects on fuel/time
- 3D route visualization

## Run Locally
1. Install dependencies:
   ```bash
   pip install -r requirements.txt
   ```
2. Start the FastAPI server:
   ```bash
   uvicorn main:app --reload
   ```
3. Open [http://127.0.0.1:8000](http://127.0.0.1:8000) in your browser.

## Deploy
To deploy on Render's free tier:
1. Push this repository to GitHub.
2. Go to [Render](https://render.com/) and create a new Web Service.
3. Connect your GitHub repository.
4. Set the Build Command to `pip install -r requirements.txt`.
5. Set the Start Command to `uvicorn main:app --host 0.0.0.0 --port $PORT`.
6. Click "Create Web Service".
