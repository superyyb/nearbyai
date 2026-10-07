import os
import tempfile

# Isolated DB and offline LLM for every test run.
os.environ.setdefault("DATABASE_URL", f"sqlite:///{tempfile.mkdtemp()}/test.db")
os.environ["LLM_BACKEND"] = "rules"
