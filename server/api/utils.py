"""Fail-closed compatibility stubs for the retired browser demo."""

async def setup_browser(*args, **kwargs):
    raise RuntimeError("Browser automation and X interactions are disabled.")


setup_agent = setup_browser
