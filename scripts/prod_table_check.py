import asyncio
import os

import asyncpg

TARGETS = ["admin_totp", "audit_log", "login_attempts"]


async def main() -> None:
    conn = await asyncpg.connect(os.environ["DATABASE_URL"])
    rows = await conn.fetch(
        """
        select table_name
        from information_schema.tables
        where table_schema='public'
          and table_name = any($1::text[])
        order by table_name
        """,
        TARGETS,
    )
    found = [row["table_name"] for row in rows]
    print("FOUND=" + ",".join(found))
    missing = sorted(set(TARGETS) - set(found))
    print("MISSING=" + ",".join(missing))
    await conn.close()


asyncio.run(main())
