# Cleanup of TEST data created during iteration 14 testing
import asyncio
import os
import re
from dotenv import load_dotenv
from motor.motor_asyncio import AsyncIOMotorClient

load_dotenv("/app/backend/.env")


async def main():
    db = AsyncIOMotorClient(os.environ["MONGO_URL"])[os.environ["DB_NAME"]]
    print("collections:", await db.list_collection_names())
    rx = {"$regex": r"^TEST"}
    print("certs:", [(c["cert_id"], c["title"], c.get("drive_link") or c.get("drive_file_id")) async for c in db.certificates.find({"title": rx})])
    for coll, field in [("events", "title"), ("tasks", "title"), ("cpd_logs", "title"), ("cpd", "title"),
                        ("cpd_resources", "title"), ("certificates", "title")]:
        if coll in await db.list_collection_names():
            r = await db[coll].delete_many({field: rx})
            print(coll, "deleted", r.deleted_count)
    pat = re.compile(r"TEST (event ddmm|case study res|collab|self task|cpd ui)|TEST_cert")
    r = await db.notifications.delete_many({"$or": [{"body": {"$regex": pat.pattern}}, {"title": {"$regex": pat.pattern}}]})
    print("notifications deleted", r.deleted_count)


asyncio.run(main())
