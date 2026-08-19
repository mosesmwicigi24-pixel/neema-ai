"""One-shot operational tools, run inside the api container:

    docker compose exec -T api python -m app.tools.<name>

Each is idempotent and prints a summary — built for the owner's terminal, not
for cron. Background loops live in app/jobs; these are for the day something
went wrong and the backlog needs a hand."""
