"""Planner entry point (mock default, optional model generation). No HTTP server, browser or daemon."""

if __package__:
    from .planner import main
else:
    from planner import main

if __name__ == "__main__":
    raise SystemExit(main())
