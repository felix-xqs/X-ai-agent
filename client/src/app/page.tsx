export default function Home() {
  return (
    <main>
      <h1>Original-content planner — offline prototype</h1>
      <p>The first version runs locally from the command line. X login, posting,
        replies and browser sessions are disabled.</p>
      <p>From the repository root:</p>
      <pre>python3 -m server plan --config planner.example.json</pre>
      <pre>python3 -m server status</pre>
      <p>See README.md for scheduling, dry-run verification and pause/retry commands.</p>
    </main>
  )
}
