import os

os.environ["DATABASE_URL"] = "sqlite:///./test_flowcare.db"
os.environ["JWT_SECRET"] = "test-secret-that-is-long-enough-for-tests"
os.environ["CORS_ORIGINS"] = "http://test"
