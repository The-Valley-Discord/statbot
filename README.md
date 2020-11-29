# statbot

## dependencies

- easiest to use if you have [nix](https://nixos.org) installed, just do `nix-shell`
- otherwise, use [poetry](https://python-poetry.org/), which is what nix uses behind the scenes
anyway. to run, enter `poetry run python3 -m sb`.
- [sqlite](https://sqlite.org) for the initial database setup, also for debugging database issues


## first steps

- create a test server from the current valley template
- create a `settings.json` with the test server's IDs, following the template in
`settings.json.example`
- create your own bot and fill in the token, add the bot to the test server
- run `sqlite3 statbot.db` and enter `.read db-migrations/<name>.sql`, for every file in that
directory, in order (currently just one)
- start the bot using `python3 -m sb` if in a nix-shell, or `poetry run python3 -m sb` if you're not

## notes on the code

- the entry point is in `__main__.py`. having shit tons of underscores everywhere is what they call
pythonic nowadays. sorry.
- run `isort sb/`, `black sb/`, and `pylint sb/` before committing and fix what they complain about
(if necessary by making them ignore a particular line)
- only change the database by creating a new file in `db-migrations/` and let the user apply it
- note to self: don't be clever
