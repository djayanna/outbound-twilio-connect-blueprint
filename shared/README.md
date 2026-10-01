A Python package that every backend app depends on as a `uv` workspace member.

```
shared/
├── job.py       # Job + JobRun Pydantic models
├── audit.py     # audit.record(db, event) writer
└── otel.py      # initOtel(service_name) — one call per app
```

