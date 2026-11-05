"""The model watcher (Build day 4), every hour at :41: it reads Anthropic's model list, records every model it has
not seen before, and names one new model for adopt/check.py to test. Its first run only records the list.

  ADOPTER_DB_URL=... ANTHROPIC_API_KEY=... python -m adopt.watch   (INPUT_MODEL names a model to check at once)
"""
import os


def candidates(new_models, champion_model):
    """The new models worth a check: Claude models other than the champion's own, newest first."""
    return [m.id for m in sorted(new_models, key=lambda m: m.created_at, reverse=True)
            if m.id.startswith("claude-") and m.id != champion_model]


def main():
    import anthropic
    import psycopg
    from agents import champion
    listed = list(anthropic.Anthropic(max_retries=2, timeout=60).models.list(limit=100, lifecycle=["active"]))
    with psycopg.connect(os.environ["ADOPTER_DB_URL"], autocommit=True) as db:  # adopter: functions only
        first_run = db.execute("select prereg.models_seen_count()").fetchone()[0] == 0
        new = [m for m in listed if db.execute("select prereg.record_model_seen(%s, %s, %s)",
                                               [m.id, m.display_name, m.created_at]).fetchone()[0]]
    found = [] if first_run else candidates(new, champion.load()["c"]["model"])
    model = os.environ.get("INPUT_MODEL", "").strip() or (found[0] if found else "")
    print(f"watch: {len(listed)} active models, {len(new)} new" + (" (the first run only records them)" if first_run else "")
          + (f"; checking {model}" if model else "; nothing to check"))
    if "GITHUB_OUTPUT" in os.environ:
        with open(os.environ["GITHUB_OUTPUT"], "a") as f:
            f.write(f"model={model}\n")


if __name__ == "__main__":
    main()
