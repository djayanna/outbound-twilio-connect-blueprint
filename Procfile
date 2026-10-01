scheduler:  uv run uvicorn scheduler.main:app --host 0.0.0.0 --port 3001 --reload
agent:      uv run uvicorn agent_connect.main:app --host 0.0.0.0 --port 3002 --reload
events:     uv run uvicorn event_ingestor.main:app --host 0.0.0.0 --port 3003 --reload
harness:    npm --prefix apps/test_harness run dev
wallboard:  npm --prefix apps/wallboard run dev
