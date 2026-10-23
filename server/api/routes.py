"""Retired browser routes. No HTTP routes are registered in this version."""

async def get_session(*args, **kwargs):
    raise RuntimeError("Browser sessions are disabled; use python3 -m server.")


run_agent = get_session
login_x = get_session
