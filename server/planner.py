"""Manual, offline content planning and simulated publication. GPL-3.0-or-later."""

import argparse
from datetime import datetime, timedelta, timezone
import hashlib
import json
from pathlib import Path
import sqlite3
import unicodedata


class PlannerError(ValueError):
    pass


def utcnow():
    return datetime.now(timezone.utc)


def timestamp(value):
    if not isinstance(value, str):
        raise PlannerError("Timestamp must be an ISO 8601 string with an offset.")
    try:
        result = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError:
        raise PlannerError("Timestamp must be ISO 8601 with an offset.")
    if result.tzinfo is None:
        raise PlannerError("Timestamp needs a timezone offset, e.g. +08:00 or Z.")
    return result.astimezone(timezone.utc)


def iso(value):
    return value.astimezone(timezone.utc).isoformat()


def fingerprint(text):
    normalized = " ".join(unicodedata.normalize("NFKC", text).casefold().split())
    return hashlib.sha256(normalized.encode("utf-8")).hexdigest()


class MockProvider:
    """Deterministic original templates, without scraping, secrets or API calls."""

    def generate(self, topic, language, style, count):
        templates = {
            "en": {
                "concise": ["{t}: start small, observe, improve.",
                            "A useful habit for {t}: write down one lesson today.",
                            "Progress on {t} starts with one repeatable step."],
                "practical": ["Try this with {t}: choose one small experiment and record what happens.",
                              "For {t}, keep a short learning log: what worked, what changed, what comes next.",
                              "Make {t} manageable: choose one action you can repeat tomorrow."],
                "question": ["What is one small step that helped you explore {t}?",
                             "When working on {t}, what would you try differently next time?",
                             "Which habit makes {t} easier to practice consistently?"]
            },
            "zh": {
                "concise": ["关于{t}：从小处开始，观察结果，再做改进。",
                            "探索{t}的一个习惯：今天记下一条收获。",
                            "把{t}变成一个可以重复的小步骤。"],
                "practical": ["试试这样探索{t}：选一个小实验，记录过程和结果。",
                              "为{t}写一份简短日志：哪些有效，哪里变化，下一步做什么。",
                              "让{t}更容易坚持：选一件明天也能重复的小事。"],
                "question": ["探索{t}时，哪个小步骤最有帮助？",
                             "关于{t}，下次你想尝试什么不同的做法？",
                             "什么习惯能让你更持续地实践{t}？"]
            }
        }
        return [item.format(t=topic) for item in templates[language][style][:count]]


def prepare(config, now=None):
    if not isinstance(config, dict):
        raise PlannerError("Configuration must be a JSON object.")
    allowed = {"topic", "language", "style", "count", "start_at", "interval_minutes", "provider"}
    if set(config) - allowed:
        raise PlannerError("Unknown configuration fields; credentials and publishing settings are not accepted.")
    if config.get("provider", "mock") != "mock":
        raise PlannerError("Only the offline mock provider is available.")
    topic = config.get("topic")
    if not isinstance(topic, str) or not topic.strip() or len(topic.strip()) > 120:
        raise PlannerError("topic must contain 1–120 characters.")
    topic = " ".join(topic.split())
    language, style = config.get("language", "en"), config.get("style", "practical")
    if language not in ("en", "zh") or style not in ("concise", "practical", "question"):
        raise PlannerError("language: en/zh; style: concise/practical/question.")
    count, interval = config.get("count", 3), config.get("interval_minutes", 60)
    if type(count) is not int or not 1 <= count <= 3:
        raise PlannerError("count must be an integer from 1 to 3.")
    if type(interval) is not int or not 1 <= interval <= 525600:
        raise PlannerError("interval_minutes must be an integer from 1 to 525600.")
    start = timestamp(config["start_at"]) if "start_at" in config else (now or utcnow())
    texts = MockProvider().generate(topic, language, style, count)
    return [dict(text=text, fingerprint=fingerprint(text), topic=topic,
                 language=language, style=style, scheduled_at=iso(start + timedelta(minutes=i * interval)))
            for i, text in enumerate(texts)]


class DisabledPublisher:
    """Reserved interface. There is deliberately no real publishing implementation."""

    def publish(self, post):
        raise PlannerError("Real publishing and all X interactions are disabled.")


class Simulator:
    def __init__(self, outcome="success"):
        if outcome not in ("success", "error", "mismatch"):
            raise PlannerError("Unknown simulation outcome.")
        self.outcome = outcome

    def publish(self, post):
        if self.outcome == "error":
            raise PlannerError("Simulated publication failure.")
        return {"mode": "dry-run", "id": "simulated-" + str(post["id"]),
                "text": post["text"] if self.outcome == "success" else "mismatched receipt",
                "fingerprint": post["fingerprint"], "verified_at": iso(utcnow())}


def verify(post, receipt):
    return (isinstance(receipt, dict) and receipt.get("mode") == "dry-run"
            and receipt.get("id") == "simulated-" + str(post["id"])
            and receipt.get("text") == post["text"]
            and receipt.get("fingerprint") == fingerprint(post["text"]))


class Queue:
    def __init__(self, path):
        self.db = sqlite3.connect(str(path), timeout=5)
        self.db.row_factory = sqlite3.Row
        self.db.executescript("""
            CREATE TABLE IF NOT EXISTS posts (
                id INTEGER PRIMARY KEY, text TEXT NOT NULL, fingerprint TEXT NOT NULL UNIQUE,
                topic TEXT NOT NULL, language TEXT NOT NULL, style TEXT NOT NULL,
                scheduled_at TEXT NOT NULL, status TEXT NOT NULL DEFAULT 'pending'
                    CHECK(status IN ('pending', 'simulated', 'failed')),
                attempts INTEGER NOT NULL DEFAULT 0, receipt TEXT, error TEXT);
            CREATE TABLE IF NOT EXISTS settings (key TEXT PRIMARY KEY, value TEXT NOT NULL);
            INSERT OR IGNORE INTO settings VALUES ('paused', 'false');
            CREATE TABLE IF NOT EXISTS events (
                id INTEGER PRIMARY KEY, at TEXT NOT NULL, post_id INTEGER,
                action TEXT NOT NULL, detail TEXT NOT NULL);
        """)

    def close(self):
        self.db.close()

    def event(self, action, post_id=None, detail=""):
        self.db.execute("INSERT INTO events(at,post_id,action,detail) VALUES (?,?,?,?)",
                        (iso(utcnow()), post_id, action, detail))

    @property
    def paused(self):
        return self.db.execute("SELECT value FROM settings WHERE key='paused'").fetchone()[0] == "true"

    def plan(self, config):
        posts = prepare(config)
        added, duplicates = [], 0
        with self.db:
            for post in posts:
                cursor = self.db.execute("""INSERT OR IGNORE INTO posts
                    (text,fingerprint,topic,language,style,scheduled_at)
                    VALUES (:text,:fingerprint,:topic,:language,:style,:scheduled_at)""", post)
                if cursor.rowcount:
                    added.append(cursor.lastrowid)
                    self.event("planned", cursor.lastrowid)
                else:
                    duplicates += 1
                    self.event("duplicate_skipped", detail=post["fingerprint"])
        return {"added": added, "duplicates_skipped": duplicates}

    def set_pause(self, paused):
        with self.db:
            self.db.execute("UPDATE settings SET value=? WHERE key='paused'", ("true" if paused else "false",))
            self.event("paused" if paused else "resumed")
        return {"paused": paused}

    def retry(self, post_id):
        with self.db:
            cursor = self.db.execute("UPDATE posts SET status='pending',error=NULL,receipt=NULL WHERE id=? AND status='failed'", (post_id,))
            if not cursor.rowcount:
                raise PlannerError("Only a failed post can be retried.")
            self.event("retry_requested", post_id)
        return {"retry_pending": post_id, "paused": self.paused}

    def run(self, now=None, outcome="success"):
        simulator = Simulator(outcome)
        now = now or utcnow()
        results = []
        # One writer, one atomic batch. A crash rolls back; simulator has no external effects.
        with self.db:
            self.db.execute("BEGIN IMMEDIATE")
            if self.paused:
                return {"mode": "dry-run", "paused": True, "results": []}
            rows = self.db.execute("SELECT * FROM posts WHERE status='pending' AND scheduled_at<=? ORDER BY scheduled_at,id", (iso(now),)).fetchall()
            for row in rows:
                post = dict(row)
                try:
                    receipt = simulator.publish(post)
                    if not verify(post, receipt):
                        raise PlannerError("Simulated receipt verification failed.")
                except PlannerError as error:
                    self.db.execute("UPDATE posts SET status='failed',attempts=attempts+1,error=? WHERE id=?", (str(error), post["id"]))
                    self.db.execute("UPDATE settings SET value='true' WHERE key='paused'")
                    self.event("simulation_failed_queue_paused", post["id"], str(error))
                    results.append({"id": post["id"], "status": "failed", "error": str(error)})
                    break
                self.db.execute("UPDATE posts SET status='simulated',attempts=attempts+1,receipt=?,error=NULL WHERE id=?", (json.dumps(receipt, ensure_ascii=False), post["id"]))
                self.event("simulation_verified", post["id"])
                results.append({"id": post["id"], "status": "simulated", "receipt": receipt})
        return {"mode": "dry-run", "paused": self.paused, "results": results}

    def status(self):
        posts = []
        for row in self.db.execute("SELECT * FROM posts ORDER BY scheduled_at,id"):
            post = dict(row)
            if post["receipt"]:
                post["receipt"] = json.loads(post["receipt"])
            posts.append(post)
        return {"mode": "dry-run", "real_publishing_enabled": False, "paused": self.paused, "posts": posts}

    def logs(self):
        return [dict(row) for row in self.db.execute("SELECT * FROM events ORDER BY id")]


def main(argv=None):
    parser = argparse.ArgumentParser(description="Offline original-content planner; never connects to X.")
    parser.add_argument("--db", default=".local/planner.sqlite3", help="local SQLite queue file")
    commands = parser.add_subparsers(dest="command", required=True)
    plan = commands.add_parser("plan", help="generate deterministic mock drafts and enqueue")
    plan.add_argument("--config", required=True)
    run = commands.add_parser("dry-run", help="simulate due posts once; then exit")
    run.add_argument("--at", help="override simulation clock (ISO 8601 with offset)")
    run.add_argument("--simulate", choices=("success", "error", "mismatch"), default="success")
    for name in ("status", "logs", "pause", "resume"):
        commands.add_parser(name)
    retry = commands.add_parser("retry", help="requeue a failed post; does not resume queue")
    retry.add_argument("id", type=int)
    args = parser.parse_args(argv)
    queue = None
    try:
        config = None
        if args.command == "plan":
            config = json.loads(Path(args.config).read_text(encoding="utf-8"))
            prepare(config)  # Validate the entire batch before opening the database.
        now = timestamp(args.at) if args.command == "dry-run" and args.at else None
        path = Path(args.db)
        path.parent.mkdir(parents=True, exist_ok=True)
        queue = Queue(path)
        if args.command == "plan":
            result = queue.plan(config)
        elif args.command == "dry-run":
            result = queue.run(now, args.simulate)
        elif args.command == "status":
            result = queue.status()
        elif args.command == "logs":
            result = queue.logs()
        elif args.command in ("pause", "resume"):
            result = queue.set_pause(args.command == "pause")
        else:
            result = queue.retry(args.id)
        print(json.dumps(result, ensure_ascii=False, indent=2))
        return 1 if args.command == "dry-run" and (result["paused"] or any(p["status"] == "failed" for p in result["results"])) else 0
    except (PlannerError, json.JSONDecodeError, UnicodeError, OSError, sqlite3.Error, OverflowError) as error:
        print(json.dumps({"error": str(error)}, ensure_ascii=False))
        return 2
    finally:
        if queue:
            queue.close()
