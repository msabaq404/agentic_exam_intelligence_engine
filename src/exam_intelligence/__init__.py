"""Exam intelligence package.

Loads environment variables from a local `.env` file if present and ensures
`.env.example` exists as a template for local development.
"""

from . import config  # noqa: F401  # load env on package import
