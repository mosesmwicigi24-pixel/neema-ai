import asyncio
from decimal import Decimal
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select, text
from sqlalchemy.exc import ProgrammingError
from sqlalchemy.dialects.postgresql import insert as pg_insert
from app.models.agent import Agent
from app.models.catalog import Catalog
from app.core.database import AsyncSessionLocal
from app.core.security import hash_password


# ── Agent seeds ───────────────────────────────────────────────────────────────

SEEDS = [
    {
        "email": "nyorojnr@gmail.com",
        "password": "MN7KNC10",
        "name": "Admin",
        "role": "admin",
        "is_available": True,
        "is_superuser": True,
    },
    {
        "email": "agent@bethanyhouse.com",
        "password": "agent123",
        "name": "Agent One",
        "role": "agent",
        "is_available": True,
        "is_superuser": False,
    },
]


# ── Catalog seeds (extracted from n8n workflow) ───────────────────────────────

CATALOG = [

    # ── Communion Wafers ─────────────────────────────────────────────────────
    {
        "sku": "WAFER-150",
        "name": "Holy Communion Wafers (150 pcs)",
        "category": "Communion Wafers",
        "price": Decimal("300"),
        "unit": "pack",
        "description": "Embossed with cross & dove. Gluten-free, 12-month shelf life. Store cool & dry.",
        "aliases": ["communion wafers 150", "hosts 150", "eucharist wafers 150"],
        "in_stock": True,
    },
    {
        "sku": "WAFER-250",
        "name": "Holy Communion Wafers (250 pcs)",
        "category": "Communion Wafers",
        "price": Decimal("500"),
        "unit": "pack",
        "description": "Embossed with cross & dove. Gluten-free, 12-month shelf life. Store cool & dry.",
        "aliases": ["communion wafers 250", "hosts 250", "eucharist wafers 250"],
        "in_stock": True,
    },
    {
        "sku": "WAFER-500",
        "name": "Holy Communion Wafers (500 pcs)",
        "category": "Communion Wafers",
        "price": Decimal("850"),
        "unit": "pack",
        "description": "Embossed with cross & dove. Gluten-free, 12-month shelf life. Store cool & dry.",
        "aliases": ["wafers", "wafers 500", "500pcs", "communion wafers", "hosts",
                    "eucharist wafers", "bread of communion"],
        "in_stock": True,
    },
    {
        "sku": "WAFER-1000",
        "name": "Holy Communion Wafers (1000 pcs)",
        "category": "Communion Wafers",
        "price": Decimal("1500"),
        "unit": "pack",
        "description": "Embossed with cross & dove. Gluten-free, 12-month shelf life. Store cool & dry.",
        "aliases": ["communion wafers 1000", "hosts 1000", "1000 pcs wafers"],
        "in_stock": True,
    },

    # ── Disposable Communion Cups ─────────────────────────────────────────────
    {
        "sku": "CUP-50",
        "name": "Disposable Communion Cups (50 pcs)",
        "category": "Communion Cups",
        "price": Decimal("500"),
        "unit": "pack",
        "description": "Clear plastic with embossed cross. Standard size, no lids. KES 10 per cup.",
        "aliases": ["communion cups 50", "plastic communion cups", "disposable cups 50"],
        "in_stock": True,
    },
    {
        "sku": "CUP-250",
        "name": "Disposable Communion Cups (250 pcs)",
        "category": "Communion Cups",
        "price": Decimal("2500"),
        "unit": "pack",
        "description": "Clear plastic with embossed cross. Standard size, no lids. KES 10 per cup.",
        "aliases": ["communion cups 250", "plastic cups 250"],
        "in_stock": True,
    },
    {
        "sku": "CUP-500",
        "name": "Disposable Communion Cups (500 pcs)",
        "category": "Communion Cups",
        "price": Decimal("5000"),
        "unit": "pack",
        "description": "Clear plastic with embossed cross. Standard size, no lids. KES 10 per cup.",
        "aliases": ["communion cups 500", "plastic cups 500"],
        "in_stock": True,
    },
    {
        "sku": "CUP-1000",
        "name": "Disposable Communion Cups (1000 pcs)",
        "category": "Communion Cups",
        "price": Decimal("10000"),
        "unit": "pack",
        "description": "Clear plastic with embossed cross. Standard size, no lids. KES 10 per cup.",
        "aliases": ["communion cups 1000", "plastic cups 1000"],
        "in_stock": True,
    },
    {
        "sku": "CUP-2500",
        "name": "Disposable Communion Cups (2500 pcs)",
        "category": "Communion Cups",
        "price": Decimal("25000"),
        "unit": "pack",
        "description": "Clear plastic with embossed cross. Standard size, no lids. KES 10 per cup.",
        "aliases": ["communion cups 2500", "plastic cups 2500"],
        "in_stock": True,
    },

    # ── Prefilled Communion Cups ──────────────────────────────────────────────
    {
        "sku": "DEVAI-25",
        "name": "Devai Prefilled Communion Cups (25 pcs)",
        "category": "Prefilled Cups",
        "price": Decimal("750"),
        "unit": "pack",
        "description": (
            "10ml cup with grape juice + wine blend and gluten wafer on top. "
            "Plastic cups in boxed packs of 25. Bethany House branding. "
            "Made-to-order, released within ~30 min. KES 30 per cup."
        ),
        "aliases": ["devai", "devai cups", "devai 25", "prefilled communion cups",
                    "ready-to-serve communion", "disposable communion packs",
                    "lord's supper packs", "devai prefilled cups"],
        "in_stock": True,
    },
    {
        "sku": "DEVAI-1L",
        "name": "Devai Non-Alcoholic Communion Wine (1L)",
        "category": "Communion Wine",
        "price": Decimal("800"),
        "unit": "bottle",
        "description": "Non-alcoholic 1L communion wine. Sold in any quantity.",
        "aliases": ["devai 1l", "devai wine", "devai non-alcoholic",
                    "non-alcoholic communion wine"],
        "in_stock": True,
    },

    # ── Communion Wine ────────────────────────────────────────────────────────
    {
        "sku": "ALTAR-750",
        "name": "Altar Wine (750ml)",
        "category": "Communion Wine",
        "price": Decimal("1800"),
        "unit": "bottle",
        "description": (
            "Fermented wine, 18% alcohol. Glass bottle, screw cap. "
            "Ready stock. 12 bottles/carton for wholesale."
        ),
        "aliases": ["altar wine", "altarwine", "alta wine", "sacramental wine",
                    "eucharistic wine", "mass wine", "altar wine 750ml"],
        "in_stock": True,
    },
    {
        "sku": "EFRAT-1L",
        "name": "Efrat Communion Wine (1L)",
        "category": "Communion Wine",
        "price": Decimal("3000"),
        "unit": "bottle",
        "description": "Efrat 1L sacramental wine. Sold in any quantity.",
        "aliases": ["efrat", "efrat wine", "efrat 1l"],
        "in_stock": True,
    },

    # ── Communion Refill Bottles ──────────────────────────────────────────────
    {
        "sku": "REFILL-500",
        "name": "Communion Refill Bottle (500ml)",
        "category": "Communion Accessories",
        "price": Decimal("1000"),
        "unit": "piece",
        "description": (
            "Translucent polyethylene with bent nozzle. Reusable and washable. "
            "No branding or customisation."
        ),
        "aliases": ["communion refill bottle 500ml", "speed bottle 500ml",
                    "pouring flask 500ml", "altar wine refiller 500ml"],
        "in_stock": True,
    },
    {
        "sku": "REFILL-1L",
        "name": "Communion Refill Bottle (1L)",
        "category": "Communion Accessories",
        "price": Decimal("1500"),
        "unit": "piece",
        "description": (
            "Translucent polyethylene with bent nozzle. Reusable and washable. "
            "No branding or customisation."
        ),
        "aliases": ["communion refill bottle 1l", "speed bottle 1l",
                    "pouring flask 1l", "altar wine refiller 1l"],
        "in_stock": True,
    },

    # ── Communion Trays ───────────────────────────────────────────────────────
    {
        "sku": "TRAY-GOLD-LID",
        "name": "Gold Communion Tray 40-Cup (with lid)",
        "category": "Communion Trays",
        "price": Decimal("23000"),
        "unit": "piece",
        "description": (
            "Holds 40 cups. Includes lid. "
            "Typical out-of-stock lead ~4 weeks. "
            "Care: wipe dry, avoid abrasives, use soft cloth."
        ),
        "aliases": ["gold tray with lid", "golden communion tray",
                    "gold 40-cup tray with lid"],
        "in_stock": True,
    },
    {
        "sku": "TRAY-GOLD-NOLID",
        "name": "Gold Communion Tray 40-Cup (no lid)",
        "category": "Communion Trays",
        "price": Decimal("15000"),
        "unit": "piece",
        "description": "Holds 40 cups, no lid. Care: wipe dry, avoid abrasives, use soft cloth.",
        "aliases": ["gold tray no lid", "gold 40-cup tray without lid"],
        "in_stock": True,
    },
    {
        "sku": "TRAY-SILVER-LID",
        "name": "Silver Communion Tray 40-Cup (with lid)",
        "category": "Communion Trays",
        "price": Decimal("20000"),
        "unit": "piece",
        "description": (
            "Holds 40 cups. Includes lid. "
            "Typical out-of-stock lead ~4 weeks. "
            "Care: wipe dry, avoid abrasives, use soft cloth."
        ),
        "aliases": ["silver tray with lid", "silver communion tray",
                    "silver 40-cup tray with lid"],
        "in_stock": True,
    },
    {
        "sku": "TRAY-40",
        "name": "Silver Communion Tray 40-Cup (no lid)",
        "category": "Communion Trays",
        "price": Decimal("13000"),
        "unit": "piece",
        "description": "Holds 40 cups, no lid. Care: wipe dry, avoid abrasives, use soft cloth.",
        "aliases": ["silver tray", "silver tray no lid",
                    "silver communion tray (40-cup)"],
        "in_stock": True,
    },
    {
        "sku": "TRAY-ALU",
        "name": "Aluminium Communion Tray 40-Cup",
        "category": "Communion Trays",
        "price": Decimal("7000"),
        "unit": "piece",
        "description": (
            "Round, polished lightweight aluminium. Holds 40 plastic cups (included). "
            "Shiny/reflective, stackable. Includes aluminium lid and handle. "
            "Grooved interior, boxed. Plain — no branding/customisation."
        ),
        "aliases": ["aluminium tray", "aluminum tray", "alu tray",
                    "communion tray aluminium", "communion tray (aluminium)"],
        "in_stock": True,
    },
    {
        "sku": "TRAY-WOODEN",
        "name": "Wooden Communion Tray 100-Cup",
        "category": "Communion Trays",
        "price": Decimal("5000"),
        "unit": "piece",
        "description": "Holds 100 cups. Includes plastic cups.",
        "aliases": ["wooden tray", "wood communion tray", "wooden 100-cup tray"],
        "in_stock": True,
    },

    # ── Bread Plates ──────────────────────────────────────────────────────────
    {
        "sku": "PLATE-GOLD",
        "name": "Gold Bread Plate",
        "category": "Communion Trays",
        "price": Decimal("14000"),
        "unit": "piece",
        "description": "Gold communion bread plate.",
        "aliases": ["gold bread plate", "gold plate"],
        "in_stock": True,
    },
    {
        "sku": "PLATE-SILVER",
        "name": "Silver Bread Plate",
        "category": "Communion Trays",
        "price": Decimal("13000"),
        "unit": "piece",
        "description": "Silver communion bread plate.",
        "aliases": ["silver bread plate", "silver plate"],
        "in_stock": True,
    },

    # ── Anointing Oil ─────────────────────────────────────────────────────────
    {
        "sku": "OIL-ELIAD-750",
        "name": "Eliad Anointing Oil (750ml)",
        "category": "Anointing Oil",
        "price": Decimal("5000"),
        "unit": "bottle",
        "description": (
            "Pure extra virgin, first cold press. "
            "Cork-wrapped seal, individually wrapped glass bottle. "
            "Imported from the Holy Land. "
            "Wholesale carton 12×KES 4,000 = KES 48,000."
        ),
        "aliases": ["eliad oil", "eliad", "anointing oil", "holy anointing oil",
                    "olive oil from the holy land", "eliad olive oil"],
        "in_stock": True,
    },

    # ── Clergy Shirts ─────────────────────────────────────────────────────────
    {
        "sku": "SHIRT-NORM",
        "name": "Clerical Shirt (Normal Collar)",
        "category": "Clergy Apparel",
        "price": Decimal("2200"),
        "unit": "piece",
        "description": "Normal collar shirt. Collar sold separately.",
        "aliases": ["clerical shirt", "clergy shirt", "roman collar shirt",
                    "normal collar shirt", "clerical shirt normal"],
        "in_stock": True,
    },
    {
        "sku": "SHIRT-BISH",
        "name": "Bishop Shirt (includes 19\" collar)",
        "category": "Clergy Apparel",
        "price": Decimal("4000"),
        "unit": "piece",
        "description": "Bishop shirt. Includes 19\" collar.",
        "aliases": ["bishop shirt", "bishop shirt black", "bishop shirt white",
                    "bishop shirt red"],
        "in_stock": True,
    },

    # ── Clerical Collars ──────────────────────────────────────────────────────
    {
        "sku": "COLLAR-8",
        "name": "Clerical Collar 8\"",
        "category": "Clergy Apparel",
        "price": Decimal("350"),
        "unit": "piece",
        "description": "8 inch clerical collar.",
        "aliases": ["collar 8", "collar 8 inch", "8 inch collar"],
        "in_stock": True,
    },
    {
        "sku": "COLLAR-10",
        "name": "Clerical Collar 10\"",
        "category": "Clergy Apparel",
        "price": Decimal("400"),
        "unit": "piece",
        "description": "10 inch clerical collar.",
        "aliases": ["collar 10", "collar 10 inch", "10 inch collar"],
        "in_stock": True,
    },
    {
        "sku": "COLLAR-12",
        "name": "Clerical Collar 12\"",
        "category": "Clergy Apparel",
        "price": Decimal("600"),
        "unit": "piece",
        "description": "12 inch clerical collar.",
        "aliases": ["collar 12", "collar 12 inch", "12 inch collar"],
        "in_stock": True,
    },
    {
        "sku": "COLLAR-14",
        "name": "Clerical Collar 14\"",
        "category": "Clergy Apparel",
        "price": Decimal("800"),
        "unit": "piece",
        "description": "14 inch clerical collar.",
        "aliases": ["collar 14", "collar 14 inch", "14 inch collar"],
        "in_stock": True,
    },
    {
        "sku": "COLLAR-17",
        "name": "Clerical Collar 17\"",
        "category": "Clergy Apparel",
        "price": Decimal("1000"),
        "unit": "piece",
        "description": "17 inch clerical collar.",
        "aliases": ["collar 17", "collar 17 inch", "17 inch collar"],
        "in_stock": True,
    },
    {
        "sku": "COLLAR-19",
        "name": "Clerical Collar 19\"",
        "category": "Clergy Apparel",
        "price": Decimal("1200"),
        "unit": "piece",
        "description": "19 inch clerical collar. Included with Bishop Shirt.",
        "aliases": ["collar 19", "collar 19 inch", "19 inch collar"],
        "in_stock": True,
    },
    {
        "sku": "COLLAR-21",
        "name": "Clerical Collar 21\"",
        "category": "Clergy Apparel",
        "price": Decimal("1500"),
        "unit": "piece",
        "description": "21 inch clerical collar.",
        "aliases": ["collar 21", "collar 21 inch", "21 inch collar",
                    "clerical collar 21 inch"],
        "in_stock": True,
    },

    # ── Vestments ─────────────────────────────────────────────────────────────
    {
        "sku": "VEST-CASSOCK",
        "name": "Cassock",
        "category": "Clergy Vestments",
        "price": Decimal("12000"),
        "unit": "piece",
        "description": (
            "Custom-made. Same price across sizes. 'Mint' poly-cotton fabric. "
            "Embroidery: logos, crosses, IHS, names "
            "(origination KES 500 once; stitching thereafter free). "
            "Alterations typically 1–3 days."
        ),
        "aliases": ["cassock", "clergy robe", "liturgical garment"],
        "in_stock": True,
    },
    {
        "sku": "VEST-ORDINATION",
        "name": "Ordination Gown",
        "category": "Clergy Vestments",
        "price": Decimal("12000"),
        "unit": "piece",
        "description": "Custom-made ordination gown. Same price across sizes.",
        "aliases": ["ordination gown", "ordination robe"],
        "in_stock": True,
    },
    {
        "sku": "VEST-CHASUBLE",
        "name": "Chasuble",
        "category": "Clergy Vestments",
        "price": Decimal("12000"),
        "unit": "piece",
        "description": "Custom-made chasuble. Same price across sizes.",
        "aliases": ["chasuble"],
        "in_stock": True,
    },
    {
        "sku": "VEST-ALB",
        "name": "Alb",
        "category": "Clergy Vestments",
        "price": Decimal("8500"),
        "unit": "piece",
        "description": "Custom-made alb. Same price across sizes.",
        "aliases": ["alb"],
        "in_stock": True,
    },
    {
        "sku": "VEST-STOLE",
        "name": "Stole",
        "category": "Clergy Vestments",
        "price": Decimal("2200"),
        "unit": "piece",
        "description": "Liturgical stole. Available in seasonal liturgical colours.",
        "aliases": ["stole", "clergy stole", "liturgical stole"],
        "in_stock": True,
    },
    {
        "sku": "VEST-MITRE",
        "name": "Mitre",
        "category": "Clergy Vestments",
        "price": Decimal("5500"),
        "unit": "piece",
        "description": "Liturgical mitre/bishop's hat.",
        "aliases": ["mitre", "bishop hat", "liturgical hat"],
        "in_stock": True,
    },
]


# ── Seed functions ────────────────────────────────────────────────────────────

async def seed_agents(db: AsyncSession) -> None:
    try:
        await db.execute(text("SELECT 1 FROM agents LIMIT 1"))
    except ProgrammingError:
        print("[seed] agents table not ready yet — skipping agent seeds")
        return

    for data in SEEDS:
        result = await db.execute(
            select(Agent).where(Agent.email == data["email"])
        )
        exists = result.scalar_one_or_none()
        if exists:
            print(f"[seed] Already exists: {data['email']}")
            continue
        agent = Agent(
            email=data["email"],
            password_hash=hash_password(data["password"]),
            name=data["name"],
            role=data["role"],
            is_available=data["is_available"],
            is_superuser=data["is_superuser"],
        )
        db.add(agent)
        print(f"[seed] Created agent: {data['email']}")

    await db.commit()


async def seed_catalog(db: AsyncSession) -> None:
    try:
        await db.execute(text("SELECT 1 FROM catalog LIMIT 1"))
    except ProgrammingError:
        print("[seed] catalog table not ready yet — skipping catalog seeds")
        return

    for item in CATALOG:
        stmt = pg_insert(Catalog).values(
            sku=item["sku"],
            name=item["name"],
            category=item["category"],
            price=item["price"],
            unit=item.get("unit"),
            description=item.get("description"),
            aliases=item.get("aliases", []),
            in_stock=item.get("in_stock", True),
        ).on_conflict_do_update(
            index_elements=["sku"],
            set_={
                "name": item["name"],
                "category": item["category"],
                "price": item["price"],
                "unit": item.get("unit"),
                "description": item.get("description"),
                "aliases": item.get("aliases", []),
                "in_stock": item.get("in_stock", True),
            },
        )
        await db.execute(stmt)

    await db.commit()
    print(f"[seed] Upserted {len(CATALOG)} catalog items.")


async def run_seeds(agents: bool = True, catalog: bool = True) -> None:
    async with AsyncSessionLocal() as db:
        if agents:
            await seed_agents(db)
        if catalog:
            await seed_catalog(db)


if __name__ == "__main__":
    import argparse

    parser = argparse.ArgumentParser(description="Run database seeds")
    parser.add_argument(
        "--agents",
        action="store_true",
        help="Seed agents only",
    )
    parser.add_argument(
        "--catalog",
        action="store_true",
        help="Seed catalog only",
    )
    args = parser.parse_args()

    # If neither flag is passed, seed everything
    seed_agents_flag  = args.agents or (not args.agents and not args.catalog)
    seed_catalog_flag = args.catalog or (not args.agents and not args.catalog)

    asyncio.run(run_seeds(agents=seed_agents_flag, catalog=seed_catalog_flag))