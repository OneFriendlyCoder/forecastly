"""Splits the playbook into sections, embeds them, and stores them in Postgres. Safe to run again."""
import re
import sys
from pathlib import Path

import psycopg

from llm import LLM, LLMError
from tools import Tools

PLAYBOOK = Path(__file__).parent / "playbook"
SAVE = "INSERT INTO playbook_chunks (chunk_id, guide, title, body, embedding) VALUES (%s, %s, %s, %s, %s::vector)"


def chunks():
    for path in sorted(PLAYBOOK.glob("*.md")):
        guide, *sections = re.split(r"^## ", path.read_text(), flags=re.MULTILINE)
        guide = guide.strip().removeprefix("# ")
        for section in sections:
            title, body = section.split("\n", 1)
            slug = re.sub(r"[^a-z0-9]+", "-", title.lower()).strip("-")
            yield f"{path.stem}#{slug}", guide, title.strip(), body.strip()


def main():
    llm, rows = LLM.from_env(), list(chunks())
    try:
        vectors = llm.embed([f"{guide}: {title}\n{body}" for _, guide, title, body in rows])
    except LLMError as error:
        sys.exit(f"playbook not indexed: {error}")
    with psycopg.connect(Tools(llm).database_url) as db:
        db.execute("DELETE FROM playbook_chunks")
        with db.cursor() as cursor:
            cursor.executemany(SAVE, [(*row, str(vector)) for row, vector in zip(rows, vectors)])
    print(f"indexed {len(rows)} playbook sections")


if __name__ == "__main__":
    main()
