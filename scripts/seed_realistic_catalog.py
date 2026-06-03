#!/usr/bin/env python3
from __future__ import annotations

import json
import os
import re
import sys
import time
import urllib.error
import urllib.parse
import urllib.request
from datetime import datetime, timezone
from typing import Any


KEYCLOAK_URL = os.environ.get("KEYCLOAK_URL", "http://keycloak:80/keycloak")
REALM = os.environ.get("REALM", "Misarch")
CLIENT_ID = os.environ.get("CLIENT_ID", "frontend")
GRANT_TYPE = os.environ.get("GRANT_TYPE", "password")
GATLING_USERNAME = os.environ.get("GATLING_USERNAME", "gatling")
GATLING_PASSWORD = os.environ.get("GATLING_PASSWORD", "123")
GRAPHQL_ENDPOINT = os.environ.get("GRAPHQL_ENDPOINT", "http://gateway:8080/graphql")
TAX_RATE_ID = os.environ.get("TAX_RATE_ID", "fd656318-91ab-4e91-8546-2fbb34a2899f")
SEED_ID = os.environ.get("SEED_ID") or datetime.now(timezone.utc).strftime("%Y%m%d%H%M%S")


CATALOG: list[dict[str, Any]] = [
    {
        "name": "Electronics & Gadgets",
        "description": "Phones, audio devices, chargers, and smart home accessories.",
        "products": [
            ("Aurora Wireless Noise-Cancelling Headphones", "Over-ear Bluetooth headphones with active noise cancellation and 40 hour battery life.", "Audio", 12999, 0.35, 80),
            ("Nova 20W USB-C Fast Charger", "Compact wall charger for phones, tablets, and earbuds.", "Charging", 1899, 0.12, 200),
            ("PixelWave 10000mAh Power Bank", "Slim portable battery pack with dual USB-C ports.", "Charging", 3499, 0.28, 150),
            ("HomeLink Smart Plug Twin Pack", "Two Wi-Fi smart plugs with scheduling and energy monitoring.", "Smart Home", 2799, 0.22, 120),
            ("ClearCall USB-C Webcam", "1080p webcam with autofocus and built-in privacy shutter.", "Computer Accessories", 5499, 0.18, 70),
            ("MetroFit Smart Fitness Band", "Water-resistant activity tracker with heart rate and sleep monitoring.", "Wearables", 5999, 0.08, 95),
            ("SoundDock Mini Bluetooth Speaker", "Portable speaker with punchy bass and splash resistance.", "Audio", 4499, 0.42, 110),
            ("FlexDesk Wireless Keyboard", "Low-profile rechargeable keyboard for laptop and tablet setups.", "Computer Accessories", 3999, 0.48, 90),
            ("GlidePro Wireless Mouse", "Ergonomic mouse with silent buttons and adjustable DPI.", "Computer Accessories", 2499, 0.16, 140),
            ("SecureView Indoor Camera", "Compact indoor security camera with motion alerts and night vision.", "Smart Home", 6999, 0.31, 75),
        ],
    },
    {
        "name": "Fashion & Apparel",
        "description": "Everyday clothing, footwear, and accessories.",
        "products": [
            ("Urban Cotton Hoodie", "Soft fleece hoodie with front pocket and relaxed fit.", "Menswear", 4999, 0.65, 120),
            ("Classic Stretch Denim Jeans", "Straight-leg jeans with durable stretch cotton fabric.", "Menswear", 6499, 0.75, 100),
            ("Luna Knit Cardigan", "Lightweight knit cardigan for layered everyday outfits.", "Womenswear", 4599, 0.42, 90),
            ("Breeze Linen Shirt", "Breathable long-sleeve linen shirt for warm weather.", "Womenswear", 3999, 0.32, 110),
            ("TrailStep Running Shoes", "Cushioned running shoes for daily training and walking.", "Footwear", 8999, 0.92, 85),
            ("CityWalk Leather Sneakers", "Minimal leather sneakers for smart casual outfits.", "Footwear", 7999, 0.88, 70),
            ("Everyday Crew Socks 6 Pack", "Soft cotton crew socks for work, gym, and travel.", "Accessories", 1499, 0.25, 180),
            ("Commuter Water-Resistant Backpack", "Laptop backpack with padded sleeve and bottle pockets.", "Bags", 5999, 0.85, 95),
            ("Merino Blend Scarf", "Warm merino blend scarf with soft brushed finish.", "Accessories", 2999, 0.2, 75),
            ("Core Training Leggings", "High-rise leggings with supportive stretch fabric.", "Sportswear", 4299, 0.3, 120),
        ],
    },
    {
        "name": "Home & Kitchen",
        "description": "Cookware, storage, cleaning tools, and home comfort products.",
        "products": [
            ("GranitePro Nonstick Frying Pan 28cm", "Durable nonstick frying pan for everyday cooking.", "Cookware", 3699, 1.1, 100),
            ("Bamboo Cutting Board Set", "Three bamboo cutting boards for meat, vegetables, and bread.", "Kitchen Tools", 2799, 1.4, 90),
            ("AromaBrew French Press 1L", "Glass French press for rich coffee and loose-leaf tea.", "Coffee & Tea", 2499, 0.75, 130),
            ("StackFresh Food Storage Containers 12 Pack", "Leak-resistant meal prep containers with snap lids.", "Storage", 3299, 1.2, 160),
            ("PureSleep Cotton Sheet Set", "Breathable cotton bedding set for double beds.", "Bedding", 5499, 1.8, 70),
            ("CozyHome Throw Blanket", "Soft woven throw blanket for sofa or bed.", "Home Textiles", 3499, 0.95, 85),
            ("SteamEase Handheld Garment Steamer", "Portable steamer for shirts, dresses, and travel clothes.", "Laundry", 4299, 0.9, 65),
            ("SparkleSpin Microfiber Mop Kit", "Flat mop kit with washable microfiber pads.", "Cleaning", 2999, 1.0, 110),
            ("QuietFlow Desk Fan", "Compact desk fan with three speed settings.", "Home Appliances", 2599, 0.68, 100),
            ("WarmGlow LED Table Lamp", "Dimmable table lamp with warm light for reading.", "Lighting", 3899, 1.05, 80),
        ],
    },
    {
        "name": "Beauty & Personal Care",
        "description": "Skincare, grooming, hair care, and daily hygiene essentials.",
        "products": [
            ("HydraFresh Face Moisturizer", "Lightweight daily moisturizer with hyaluronic acid.", "Skincare", 1999, 0.12, 160),
            ("GlowDaily Vitamin C Serum", "Brightening facial serum for morning skincare routines.", "Skincare", 2499, 0.08, 140),
            ("CalmSkin Gentle Cleanser", "Fragrance-free cleanser for sensitive skin.", "Skincare", 1599, 0.22, 170),
            ("SilkRepair Shampoo", "Nourishing shampoo for dry and damaged hair.", "Hair Care", 1299, 0.55, 180),
            ("SilkRepair Conditioner", "Smoothing conditioner with argan oil blend.", "Hair Care", 1399, 0.55, 175),
            ("FreshMint Electric Toothbrush", "Rechargeable toothbrush with two brushing modes.", "Oral Care", 3999, 0.32, 95),
            ("SmoothEdge Beard Trimmer", "Cordless trimmer with adjustable length combs.", "Grooming", 3499, 0.28, 85),
            ("SoftTouch Makeup Brush Set", "Ten-piece brush set for face and eye makeup.", "Makeup Tools", 2299, 0.2, 120),
            ("PureCotton Cleansing Pads 200 Pack", "Soft cotton pads for makeup removal and skincare.", "Skincare", 799, 0.18, 250),
            ("OceanBreeze Body Wash", "Refreshing body wash with mild cleansing formula.", "Bath & Body", 999, 0.62, 200),
        ],
    },
    {
        "name": "Sports & Outdoors",
        "description": "Fitness, camping, cycling, and outdoor activity gear.",
        "products": [
            ("FlexCore Yoga Mat", "Non-slip yoga mat with carrying strap.", "Fitness", 2999, 1.25, 120),
            ("IronGrip Adjustable Dumbbell Pair", "Space-saving dumbbells for home strength training.", "Fitness", 7999, 10.0, 45),
            ("TrailPeak Hiking Backpack 30L", "Lightweight hiking backpack with rain cover.", "Hiking", 6499, 1.1, 70),
            ("HydroRun Stainless Steel Bottle", "Insulated water bottle that keeps drinks cold for 24 hours.", "Hydration", 2499, 0.38, 140),
            ("CampLite LED Lantern", "Rechargeable camping lantern with hanging hook.", "Camping", 3199, 0.5, 95),
            ("PacePro Jump Rope", "Adjustable speed rope for cardio workouts.", "Fitness", 1199, 0.18, 180),
            ("GripMaster Training Gloves", "Breathable workout gloves with wrist support.", "Fitness", 1899, 0.16, 130),
            ("AllWeather Picnic Blanket", "Water-resistant foldable blanket for parks and beaches.", "Outdoor Living", 2799, 0.9, 90),
            ("CityRide Bicycle Lock", "Hardened steel U-lock with two keys.", "Cycling", 3499, 1.3, 80),
            ("Summit Trekking Poles", "Adjustable aluminum trekking poles for hiking trails.", "Hiking", 4499, 0.62, 75),
        ],
    },
    {
        "name": "Toys & Games",
        "description": "Creative toys, puzzles, family games, and learning kits.",
        "products": [
            ("BuildBox City Blocks 500 Piece Set", "Colorful building blocks for open-ended city play.", "Building Toys", 3999, 1.6, 100),
            ("Jungle Friends Plush Elephant", "Soft plush elephant toy for toddlers.", "Plush Toys", 1899, 0.35, 120),
            ("Space Explorer Puzzle 1000 Pieces", "Detailed space-themed jigsaw puzzle for families.", "Puzzles", 1999, 0.75, 95),
            ("MathQuest Learning Cards", "Flash cards for practicing arithmetic and logic.", "Learning Toys", 1299, 0.28, 150),
            ("Rainbow Art Supply Kit", "Markers, crayons, pencils, and sketch pad in one case.", "Arts & Crafts", 2499, 0.9, 110),
            ("Family Strategy Board Game", "Easy-to-learn board game for two to five players.", "Board Games", 3299, 1.1, 85),
            ("Mini Chef Pretend Kitchen Set", "Pretend cooking set with pans, utensils, and play food.", "Pretend Play", 2999, 1.0, 80),
            ("Remote Control Rally Car", "Rechargeable RC car for indoor and outdoor play.", "Vehicles", 4499, 0.85, 65),
            ("Dino Dig Science Kit", "Excavation kit with dinosaur fossils and tools.", "STEM Toys", 2199, 0.72, 105),
            ("Magnetic Tile Starter Pack", "Magnetic construction tiles for shapes and structures.", "Building Toys", 3499, 1.2, 90),
        ],
    },
    {
        "name": "Books & Stationery",
        "description": "Books, notebooks, writing tools, and desk essentials.",
        "products": [
            ("Modern Web Architecture Handbook", "Practical guide to scalable web systems and APIs.", "Books", 3499, 0.7, 70),
            ("Data Science Field Notes", "Accessible introduction to applied data analysis.", "Books", 2999, 0.65, 80),
            ("Everyday Meal Planner Notebook", "Weekly meal planning notebook with grocery lists.", "Notebooks", 1299, 0.35, 130),
            ("Premium Hardcover Journal", "Dotted hardcover journal for notes and sketches.", "Notebooks", 1799, 0.42, 120),
            ("SmoothWrite Gel Pens 12 Pack", "Assorted black gel pens with quick-dry ink.", "Writing", 999, 0.18, 200),
            ("DeskMate Sticky Notes Set", "Colorful sticky notes in multiple sizes.", "Office Supplies", 699, 0.22, 220),
            ("A4 Recycled Printer Paper 500 Sheets", "Recycled copy paper for home and office printers.", "Paper", 799, 2.5, 180),
            ("Minimal Desk Organizer", "Wooden organizer for pens, notes, and small accessories.", "Desk Accessories", 2499, 0.9, 90),
            ("Academic Wall Planner", "Large wall calendar for semester and project planning.", "Planning", 1499, 0.25, 110),
            ("Watercolor Starter Pad", "Cold-press watercolor paper for beginners.", "Art Supplies", 1199, 0.48, 100),
        ],
    },
    {
        "name": "Grocery & Gourmet",
        "description": "Pantry staples, coffee, snacks, and specialty food.",
        "products": [
            ("Mountain Roast Coffee Beans 1kg", "Medium roast whole beans with chocolate and nut notes.", "Coffee", 1899, 1.05, 140),
            ("Organic Extra Virgin Olive Oil 750ml", "Cold-pressed olive oil for salads and cooking.", "Pantry", 1399, 0.85, 130),
            ("Artisan Fusilli Pasta 500g", "Bronze-cut pasta made from durum wheat semolina.", "Pantry", 399, 0.52, 220),
            ("Tomato Basil Pasta Sauce 680g", "Slow-cooked tomato sauce with basil and garlic.", "Pantry", 499, 0.82, 200),
            ("Crunchy Almond Granola 750g", "Oat granola with almonds, seeds, and honey.", "Breakfast", 699, 0.78, 180),
            ("Dark Chocolate Sea Salt Bar", "70 percent cocoa chocolate with sea salt flakes.", "Snacks", 299, 0.12, 260),
            ("Green Garden Tea Selection", "Assorted green tea bags in a gift box.", "Tea", 899, 0.2, 150),
            ("Wildflower Honey 500g", "Pure wildflower honey in a glass jar.", "Pantry", 799, 0.72, 160),
            ("Protein Snack Mix 400g", "Roasted nuts, seeds, and dried fruit blend.", "Snacks", 899, 0.45, 170),
            ("Sparkling Lemon Water 12 Pack", "Cans of lightly sparkling lemon-flavored water.", "Beverages", 999, 4.2, 120),
        ],
    },
    {
        "name": "Office & Productivity",
        "description": "Work-from-home equipment and productivity accessories.",
        "products": [
            ("ErgoLift Laptop Stand", "Adjustable aluminum stand for laptops up to 16 inches.", "Workspace", 3499, 0.9, 100),
            ("FocusFlow Desk Pad", "Large vegan leather desk mat for keyboard and mouse.", "Workspace", 1999, 0.65, 140),
            ("QuietType Mechanical Keyboard", "Compact mechanical keyboard with tactile switches.", "Computer Accessories", 8999, 0.8, 70),
            ("ClearVoice USB Microphone", "Plug-and-play microphone for calls and recording.", "Audio", 5999, 0.55, 85),
            ("TaskBoard Magnetic Whiteboard", "Wall-mounted whiteboard with markers and magnets.", "Planning", 4499, 2.0, 60),
            ("CableNest Management Kit", "Cable clips, sleeves, and ties for tidy desks.", "Organization", 1499, 0.22, 180),
            ("ArchiveBox Document Storage 10 Pack", "Cardboard storage boxes for files and documents.", "Storage", 2499, 3.0, 110),
            ("LED Monitor Light Bar", "Screen-mounted light bar with adjustable brightness.", "Lighting", 4999, 0.45, 75),
            ("Daily Focus Planner", "Undated planner for priorities, notes, and habits.", "Planning", 1699, 0.38, 130),
            ("Dual Monitor Arm", "Adjustable desk mount for two monitors.", "Workspace", 11999, 4.2, 45),
        ],
    },
    {
        "name": "Pet Supplies",
        "description": "Food, toys, grooming, and comfort products for pets.",
        "products": [
            ("ComfortPaws Orthopedic Dog Bed", "Supportive washable dog bed for medium dogs.", "Dog Supplies", 5999, 2.4, 65),
            ("WhiskerFresh Clumping Cat Litter 10kg", "Low-dust clumping litter with odor control.", "Cat Supplies", 1499, 10.2, 120),
            ("Crunchy Chicken Dog Treats 500g", "Oven-baked chicken treats for training rewards.", "Dog Food", 799, 0.55, 180),
            ("Salmon Bites Cat Treats 120g", "Soft salmon treats for cats of all ages.", "Cat Food", 499, 0.14, 200),
            ("TangleFree Pet Grooming Brush", "Gentle brush for removing loose fur and tangles.", "Grooming", 1299, 0.18, 150),
            ("Reflective Dog Leash", "Durable leash with reflective stitching for night walks.", "Dog Supplies", 1699, 0.25, 140),
            ("FeatherPlay Cat Wand Toy", "Interactive wand toy with replaceable feathers.", "Cat Toys", 699, 0.08, 210),
            ("SlowFeed Pet Bowl", "Non-slip bowl designed to slow down fast eaters.", "Feeding", 1199, 0.35, 160),
            ("TravelPet Water Bottle", "Portable pet water bottle with built-in drinking tray.", "Travel", 1599, 0.22, 130),
            ("Aquarium Care Starter Kit", "Basic water care tools for small aquariums.", "Aquatic Supplies", 2499, 0.7, 80),
        ],
    },
]


def post_json(url: str, payload: dict[str, Any], headers: dict[str, str] | None = None) -> dict[str, Any]:
    request = urllib.request.Request(
        url,
        data=json.dumps(payload).encode("utf-8"),
        headers={"Content-Type": "application/json", **(headers or {})},
        method="POST",
    )
    try:
        with urllib.request.urlopen(request, timeout=60) as response:
            return json.loads(response.read().decode("utf-8"))
    except urllib.error.HTTPError as exc:
        body = exc.read().decode("utf-8", errors="replace")
        raise RuntimeError(f"HTTP {exc.code} from {url}: {body[:1000]}") from exc


def get_access_token() -> str:
    body = urllib.parse.urlencode(
        {
            "grant_type": GRANT_TYPE,
            "client_id": CLIENT_ID,
            "username": GATLING_USERNAME,
            "password": GATLING_PASSWORD,
        }
    ).encode("utf-8")
    request = urllib.request.Request(
        f"{KEYCLOAK_URL}/realms/{REALM}/protocol/openid-connect/token",
        data=body,
        headers={"Content-Type": "application/x-www-form-urlencoded"},
        method="POST",
    )
    with urllib.request.urlopen(request, timeout=30) as response:
        payload = json.loads(response.read().decode("utf-8"))
    token = payload.get("access_token")
    if not isinstance(token, str) or not token:
        raise RuntimeError(f"failed to retrieve access token: {payload}")
    return token


def graphql(query: str, variables: dict[str, Any] | None, token: str) -> dict[str, Any]:
    payload = post_json(
        GRAPHQL_ENDPOINT,
        {"query": query, "variables": variables or {}},
        {"Authorization": f"Bearer {token}"},
    )
    if payload.get("errors"):
        raise RuntimeError(json.dumps(payload["errors"], ensure_ascii=False))
    return payload["data"]


def slugify(value: str) -> str:
    value = re.sub(r"[^A-Za-z0-9]+", "-", value).strip("-")
    return value.upper()[:64]


def create_category(token: str, category: dict[str, Any]) -> dict[str, Any]:
    mutation = """
    mutation CreateCategory($input: CreateCategoryInput!) {
      createCategory(input: $input) {
        id
        name
        description
        characteristics(first: 10) {
          nodes {
            id
            name
          }
        }
      }
    }
    """
    data = graphql(
        mutation,
        {
            "input": {
                "name": category["name"],
                "description": category["description"],
                "categoricalCharacteristics": [
                    {
                        "name": "Product Type",
                        "description": f"Product type within {category['name']}",
                    }
                ],
                "numericalCharacteristics": [],
            }
        },
        token,
    )
    created = data["createCategory"]
    characteristics = created["characteristics"]["nodes"]
    if not characteristics:
        raise RuntimeError(f"category has no characteristic: {created}")
    return {
        "id": created["id"],
        "name": created["name"],
        "description": created["description"],
        "characteristic_id": characteristics[0]["id"],
        "characteristic_name": characteristics[0]["name"],
    }


def create_product(
    token: str,
    category: dict[str, Any],
    product: tuple[str, str, str, int, float, int],
    product_index: int,
) -> dict[str, Any]:
    name, description, product_type, price_cents, weight_kg, stock = product
    mutation = """
    mutation CreateProduct($input: CreateProductInput!) {
      createProduct(input: $input) {
        id
        internalName
        isPubliclyVisible
        defaultVariant {
          id
          isPubliclyVisible
          currentVersion {
            id
            name
            description
            retailPrice
            weight
          }
        }
        categories(first: 10) {
          nodes {
            id
            name
          }
        }
      }
    }
    """
    internal_name = f"SEED-{SEED_ID}-{product_index:03d}-{slugify(name)}"
    data = graphql(
        mutation,
        {
            "input": {
                "categoryIds": [category["id"]],
                "defaultVariant": {
                    "initialVersion": {
                        "canBeReturnedForDays": 30,
                        "categoricalCharacteristicValues": [
                            {
                                "characteristicId": category["characteristic_id"],
                                "value": product_type,
                            }
                        ],
                        "description": description,
                        "mediaIds": [],
                        "name": name,
                        "numericalCharacteristicValues": [],
                        "retailPrice": price_cents,
                        "taxRateId": TAX_RATE_ID,
                        "weight": weight_kg,
                    },
                    "isPubliclyVisible": True,
                },
                "internalName": internal_name,
                "isPubliclyVisible": True,
            }
        },
        token,
    )
    created = data["createProduct"]
    variant_id = created["defaultVariant"]["id"]
    inventory_count = create_inventory(token, variant_id, stock)
    version = created["defaultVariant"]["currentVersion"]
    return {
        "product_id": created["id"],
        "variant_id": variant_id,
        "version_id": version["id"],
        "name": version["name"],
        "description": version["description"],
        "category": category["name"],
        "product_type": product_type,
        "retail_price_cents": version["retailPrice"],
        "weight": version["weight"],
        "stock_created": stock,
        "inventory_count_after_restock": inventory_count,
        "internal_name": created["internalName"],
    }


def create_inventory(token: str, variant_id: str, stock: int) -> int:
    mutation = """
    mutation Restock($input: CreateProductItemBatchInput!) {
      createProductItemBatch(input: $input) {
        id
        inventoryStatus
        productVariant {
          id
          inventoryCount
        }
      }
    }
    """
    data = graphql(
        mutation,
        {"input": {"productVariantId": variant_id, "number": stock}},
        token,
    )
    items = data["createProductItemBatch"]
    if len(items) != stock:
        raise RuntimeError(f"expected {stock} inventory items, got {len(items)}")
    return items[0]["productVariant"]["inventoryCount"]


def run() -> dict[str, Any]:
    start = time.perf_counter()
    token = get_access_token()
    categories: list[dict[str, Any]] = []
    products: list[dict[str, Any]] = []
    product_index = 0

    for category in CATALOG:
        created_category = create_category(token, category)
        categories.append(created_category)
        for product in category["products"]:
            product_index += 1
            products.append(create_product(token, created_category, product, product_index))

    return {
        "created_at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        "seed_id": SEED_ID,
        "category_count": len(categories),
        "product_count": len(products),
        "inventory_items_created": sum(int(product["stock_created"]) for product in products),
        "duration_ms": round((time.perf_counter() - start) * 1000, 2),
        "categories": categories,
        "products": products,
    }


def main() -> int:
    try:
        print(json.dumps(run(), ensure_ascii=False, indent=2))
    except Exception as exc:
        print(json.dumps({"ok": False, "error": str(exc)}, ensure_ascii=False, indent=2), file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
