from __future__ import annotations

import json
import tempfile
import unittest
import zipfile
from decimal import Decimal
from pathlib import Path

from o_alquimista.parser import snapshot_from_zip
from o_alquimista.report import build_markdown


def _base_files() -> dict[str, object]:
    return {
        "Money.json": {
            "GameVersion": "synthetic-version",
            "OnlineBalance": 100,
            "Networth": 200,
            "LifetimeEarnings": 300,
            "WeeklyDepositSum": 0,
        },
        "Products.json": {
            "DiscoveredProducts": ["product-a"],
            "ListedProducts": ["product-a"],
            "ProductPrices": [{"String": "product-a", "Int": 10}],
            "MixRecipes": [],
            "ActiveMixOperation": {},
        },
        "Time.json": {
            "GameVersion": "synthetic-version",
            "ElapsedDays": 1,
            "TimeOfDay": 600,
            "Playtime": 60,
        },
        "Rank.json": {
            "Rank": 1,
            "Tier": 1,
            "XP": 0,
            "TotalXP": 0,
            "UnlockedRegions": [],
        },
        "NPCs.json": {"NPCs": []},
    }


def _item(item_id: str, quantity: int) -> str:
    return json.dumps(
        {
            "DataType": "ItemData",
            "DataVersion": 0,
            "GameVersion": "synthetic-version",
            "ID": item_id,
            "Quantity": quantity,
        }
    )


def _object(
    data_type: str,
    item_id: str,
    guid: str,
    **state: object,
) -> dict[str, object]:
    base_data = {
        "DataType": data_type,
        "DataVersion": 0,
        "GameVersion": "synthetic-version",
        "GUID": guid,
        "ItemString": _item(item_id, 1),
        **state,
    }
    return {
        "DataType": data_type,
        "DataVersion": 0,
        "GameVersion": "synthetic-version",
        "BaseData": json.dumps(base_data),
        "AdditionalDatas": [],
    }


def _save_files() -> dict[str, object]:
    files = _base_files()
    files["Properties/laboratory.json"] = {
        "PropertyCode": "laboratory",
        "IsOwned": True,
        "Employees": [],
        "Objects": [
            _object(
                "PlaceableStorageData",
                "mediumstoragerack",
                "synthetic-storage-guid",
                Contents={
                    "Items": [_item("product-a", 3), ""],
                    "SlotFilters": [],
                },
            ),
            _object(
                "PackagingStationData",
                "packagingstation",
                "synthetic-packaging-guid",
                Contents={
                    "Items": [_item("jar", 2), "", ""],
                    "SlotFilters": [],
                },
            ),
            _object(
                "MixingStationData",
                "mixingstation",
                "synthetic-mixing-guid",
                MixerContents={"Items": [""], "SlotFilters": []},
                OutputContents={"Items": [""], "SlotFilters": []},
                ProductContents={"Items": [""], "SlotFilters": []},
                CurrentMixOperation={
                    "IngredientID": "ingredient-a",
                    "ProductID": "product-a",
                    "Quantity": 1,
                },
                CurrentMixTime=15,
            ),
            _object(
                "PotData",
                "plasticpot",
                "synthetic-pot-guid",
                PlantData={
                    "SeedID": "seed-a",
                    "GrowthProgress": 0.25,
                },
                WaterLevel=0.5,
            ),
        ],
    }
    return files


def _create_zip(
    destination: Path,
    files: dict[str, object] | None = None,
) -> None:
    with zipfile.ZipFile(destination, mode="w") as archive:
        for relative, value in (files or _save_files()).items():
            archive.writestr(relative, json.dumps(value))


class OperationalObjectParsingTests(unittest.TestCase):
    def test_nested_base_data_is_normalized_without_inventing_throughput(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            archive = Path(temporary) / "save.zip"
            _create_zip(archive)

            snapshot = snapshot_from_zip(archive).to_dict()
            prop = snapshot["properties"][0]
            objects = {item["item_id"]: item for item in prop["objects"]}

            self.assertEqual(prop["object_count"], 4)
            self.assertEqual(
                prop["object_types"],
                {
                    "PlaceableStorageData": 1,
                    "PackagingStationData": 1,
                    "MixingStationData": 1,
                    "PotData": 1,
                },
            )
            self.assertEqual(objects["mediumstoragerack"]["category"], "storage")
            self.assertEqual(objects["packagingstation"]["category"], "packaging")
            self.assertEqual(objects["mixingstation"]["category"], "mixing")
            self.assertEqual(objects["plasticpot"]["category"], "cultivation")
            self.assertEqual(
                objects["mixingstation"]["operational_state"],
                "active",
            )
            self.assertEqual(objects["plasticpot"]["operational_state"], "active")
            self.assertEqual(
                objects["plasticpot"]["state"]["growth_progress"],
                0.25,
            )
            self.assertNotIn(
                "synthetic-storage-guid",
                objects["mediumstoragerack"]["instance_id"],
            )

    def test_container_slots_and_property_inventory_are_observed(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            archive = Path(temporary) / "save.zip"
            _create_zip(archive)

            snapshot = snapshot_from_zip(archive).to_dict()
            prop = snapshot["properties"][0]
            objects = {item["item_id"]: item for item in prop["objects"]}
            storage = objects["mediumstoragerack"]["containers"][0]
            packaging = objects["packagingstation"]["containers"][0]

            self.assertEqual(storage["slot_count"], 2)
            self.assertEqual(storage["occupied_slot_count"], 1)
            self.assertEqual(
                storage["inventory"]["quantities"]["product-a"],
                Decimal("3"),
            )
            self.assertEqual(packaging["slot_count"], 3)
            self.assertEqual(packaging["occupied_slot_count"], 1)
            self.assertEqual(
                prop["inventory"]["quantities"],
                {"product-a": Decimal("3"), "jar": Decimal("2")},
            )

    def test_operational_instance_ids_are_deterministic(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            archive = Path(temporary) / "save.zip"
            _create_zip(archive)

            first = snapshot_from_zip(archive).to_dict()
            second = snapshot_from_zip(archive).to_dict()

            self.assertEqual(
                [item["instance_id"] for item in first["properties"][0]["objects"]],
                [item["instance_id"] for item in second["properties"][0]["objects"]],
            )

    def test_legacy_top_level_inventory_remains_supported(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            archive = Path(temporary) / "save.zip"
            files = _base_files()
            files["Properties/legacy.json"] = {
                "PropertyCode": "legacy",
                "IsOwned": True,
                "Employees": [],
                "Objects": [
                    {
                        "ObjectType": "PlaceableStorageData",
                        "ItemString": _item("legacyrack", 1),
                        "Inventory": {
                            "Items": [_item("product-a", 2)],
                            "SlotFilters": [],
                        },
                    }
                ],
            }
            _create_zip(archive, files)

            prop = snapshot_from_zip(archive).to_dict()["properties"][0]
            operational_object = prop["objects"][0]

            self.assertEqual(
                operational_object["data_type"],
                "PlaceableStorageData",
            )
            self.assertEqual(operational_object["item_id"], "legacyrack")
            self.assertEqual(
                prop["inventory"]["quantities"]["product-a"],
                Decimal("2"),
            )

    def test_snapshot_report_exposes_only_observed_slot_counts(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            archive = Path(temporary) / "save.zip"
            _create_zip(archive)

            report = build_markdown(snapshot_from_zip(archive).to_dict())

            self.assertIn("## Instalações observadas", report)
            self.assertIn("`mixingstation`", report)
            self.assertIn("Slots representam recipientes observados", report)
            self.assertNotIn("por hora", report.split("## Instalações observadas")[0])


if __name__ == "__main__":
    unittest.main()
