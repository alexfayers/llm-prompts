import os

if os.environ.get("DEMO_ENV") != "test":
    raise RuntimeError("unknown environment")
