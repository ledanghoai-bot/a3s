"""CA Directive 404 §2C — CLI tra vet bao phi theo command_key (read-only, redacted). Dung cho evidence soak.

  docker compose -f docker-compose.prod.yml exec -T -e PYTHONPATH=/srv api python scripts/m7_quote_trace.py <command_key>
"""
import asyncio
import json
import sys

import asyncpg

from app.config import settings
from app.services.fulfillment import quote_trace


async def main(key: str) -> None:
    c = await asyncpg.connect(settings.database_url.replace("+asyncpg", ""))
    try:
        await c.execute("SET default_transaction_read_only = on")
        print(json.dumps(await quote_trace.trace(c, key), ensure_ascii=False, indent=2, default=str))
    finally:
        await c.close()


if __name__ == "__main__":
    if len(sys.argv) != 2:
        sys.exit("usage: m7_quote_trace.py <command_key>")
    asyncio.run(main(sys.argv[1]))
