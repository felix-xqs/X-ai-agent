"""Offline planner entry point. No HTTP server, browser, credentials or daemon."""

if __package__:
    from .planner import main
else:
    from planner import main

if __name__ == "__main__":
    raise SystemExit(main())
