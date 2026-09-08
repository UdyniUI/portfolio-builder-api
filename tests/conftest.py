import os
import tempfile


test_root = tempfile.mkdtemp(prefix="portfoliosos-tests-")
test_database = os.path.join(test_root, "test.db")
os.environ["DATABASE_URL"] = f"sqlite+pysqlite:///{test_database}"
os.environ["DEBUG"] = "false"
os.environ["ENVIRONMENT"] = "test"
os.environ["RESUME_UPLOAD_DIR"] = os.path.join(test_root, "uploads")
