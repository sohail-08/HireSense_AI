"""Set synthetic test configuration before any application imports.

Do not let collection order cache developer credentials before test_auth loads.
These values affect only the test process, never the root .env or real database.
"""
import os

os.environ["DATABASE_URL"] = "sqlite://"
os.environ["JWT_SECRET_KEY"] = "test-only-jwt-secret-key-with-at-least-32-characters"
os.environ["INTERVIEWER_EMAIL"] = "interviewer@hiresense.com"
os.environ["INTERVIEWER_PASSWORD"] = "TestInterviewerPassword123!"
