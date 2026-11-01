"""The read-only tools shared by the agent and the MCP server."""
import json
import os
import urllib.error
import urllib.parse
import urllib.request

import psycopg

SEARCH = """SELECT chunk_id, guide, title, body FROM playbook_chunks
ORDER BY embedding <=> %s::vector LIMIT 3"""

DEFINITIONS = [
    {"type": "function", "function": {
        "name": "get_recent_events",
        "description": "The deal's newest activity events: emails, replies, meetings and close date changes.",
        "parameters": {"type": "object", "required": ["deal_id"], "properties": {
            "deal_id": {"type": "string"}, "limit": {"type": "integer", "minimum": 1, "maximum": 10}}}}},
    {"type": "function", "function": {
        "name": "search_playbook",
        "description": "Search the sales playbook for advice on a situation. Returns sections with a chunk_id to cite.",
        "parameters": {"type": "object", "required": ["query"], "properties": {"query": {"type": "string"}}}}},
]


class DealNotFound(Exception):
    pass


class Tools:
    def __init__(self, llm, api_url=None, database_url=None):
        self.llm = llm
        self.api_url = api_url or os.environ.get("API_URL", "http://localhost:8080")
        self.database_url = database_url or os.environ.get(
            "DATABASE_URL", "postgres://pulse:pulse@localhost:5432/pipeline_pulse")

    def _get(self, path):
        try:
            with urllib.request.urlopen(self.api_url + path, timeout=10) as response:
                return json.load(response)
        except urllib.error.HTTPError as error:
            if error.code == 404:
                raise DealNotFound(path) from error
            raise

    def list_at_risk(self, limit=50):
        return self._get(f"/deals/at-risk?limit={int(limit)}")["deals"]

    def get_deal(self, deal_id):
        return self._get(f"/deals/{urllib.parse.quote(deal_id, safe='')}")

    def get_recent_events(self, deal_id, limit=20):
        return self._get(f"/deals/{urllib.parse.quote(deal_id, safe='')}/events?limit={int(limit)}")["events"]

    def search_playbook(self, query):
        vector = self.llm.embed([query], "query")[0]
        with psycopg.connect(self.database_url) as db:
            rows = db.execute(SEARCH, (str(vector),)).fetchall()
        return [dict(zip(("chunk_id", "guide", "title", "body"), row)) for row in rows]
