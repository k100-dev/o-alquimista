from __future__ import annotations

import json
import tempfile
import unittest
import zipfile
from copy import deepcopy
from decimal import Decimal
from pathlib import Path

from o_alquimista.analysis import (
    RecommendationContext,
    build_timeline_entry,
    compare_snapshots,
    generate_recommendations,
)
from o_alquimista.memory_reports import build_comparison_markdown
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
            self.assertEqual(
                objects["mixingstation"]["state"]["operation"],
                {
                    "ingredient_id": "ingredient-a",
                    "product_id": "product-a",
                    "product_quality": None,
                    "quantity": Decimal("1"),
                },
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

    def test_operational_state_changes_are_compared_by_stable_instance(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            archive = Path(temporary) / "save.zip"
            _create_zip(archive)
            previous = snapshot_from_zip(archive).to_dict()
            current = deepcopy(previous)
            mixing = next(
                item
                for item in current["properties"][0]["objects"]
                if item["item_id"] == "mixingstation"
            )
            mixing["state"]["operation"]["product_id"] = "product-b"
            mixing["state"]["current_mix_time"] = 1

            comparison = compare_snapshots(
                previous,
                current,
                previous_snapshot_id="snapshot-a",
                current_snapshot_id="snapshot-b",
                previous_campaign_id="campaign-a",
                current_campaign_id="campaign-a",
            )
            changes = {
                change.field: change
                for change in comparison.operational_changes["equipment"]
            }

            self.assertEqual(
                changes[mixing["instance_id"]].status,
                "changed",
            )
            report = build_comparison_markdown(comparison)
            self.assertIn("## Mudanças operacionais", report)
            self.assertIn("`equipment`", report)
            self.assertIn("laboratory / mixingstation", report)

    def test_timeline_contains_observed_operational_totals(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            archive = Path(temporary) / "save.zip"
            _create_zip(archive)
            snapshot = snapshot_from_zip(archive).to_dict()

            timeline = build_timeline_entry(
                snapshot,
                snapshot_id="snapshot-a",
                import_id="import-a",
                campaign_id="campaign-a",
                archive_hash="synthetic-hash",
            )

            self.assertEqual(timeline.operational_summary["equipment"], 4)
            self.assertEqual(timeline.operational_summary["active_equipment"], 2)
            self.assertEqual(timeline.operational_summary["observed_slots"], 8)
            self.assertEqual(timeline.operational_summary["occupied_slots"], 2)

    def test_legacy_snapshot_does_not_infer_equipment_removal(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            archive = Path(temporary) / "save.zip"
            _create_zip(archive)
            current = snapshot_from_zip(archive).to_dict()
            previous = deepcopy(current)
            for prop in previous["properties"]:
                prop.pop("objects", None)

            comparison = compare_snapshots(
                previous,
                current,
                previous_snapshot_id="snapshot-legacy",
                current_snapshot_id="snapshot-current",
                previous_campaign_id="campaign-a",
                current_campaign_id="campaign-a",
            )

            self.assertEqual(
                comparison.operational_changes["equipment"][0].status,
                "unknown",
            )

    def test_operational_rules_prioritize_idle_cultivation_and_storage(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            archive = Path(temporary) / "save.zip"
            _create_zip(archive)
            snapshot = snapshot_from_zip(archive).to_dict()
            objects = snapshot["properties"][0]["objects"]
            pot = next(item for item in objects if item["category"] == "cultivation")
            storage = next(item for item in objects if item["category"] == "storage")
            pot["operational_state"] = "idle"
            pot["state"]["has_plant"] = False
            storage["containers"][0]["slot_count"] = 5
            storage["containers"][0]["occupied_slot_count"] = 5

            recommendations = generate_recommendations(
                RecommendationContext(
                    campaign_id="campaign-a",
                    snapshot_id="snapshot-a",
                    snapshot=snapshot,
                    snapshot_count=2,
                )
            )
            rules = {item.rule_id for item in recommendations}

            self.assertIn("operations.idle-cultivation.v1", rules)
            self.assertIn("operations.storage-pressure.v1", rules)

    def test_processing_equipment_and_employee_roles_are_normalized(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            archive = Path(temporary) / "save.zip"
            files = _base_files()
            files["Properties/laboratory.json"] = {
                "PropertyCode": "laboratory",
                "IsOwned": True,
                "Employees": [
                    {
                        "DataType": "ChemistData",
                        "BaseData": {
                            "DataType": "ChemistData",
                            "ID": "synthetic-chemist",
                            "PaidForToday": True,
                        },
                        "AdditionalDatas": [
                            {
                                "Contents": {
                                    "Stations": {
                                        "ObjectGUIDs": [
                                            "synthetic-station-a",
                                            "synthetic-station-b",
                                        ]
                                    }
                                }
                            }
                        ],
                    }
                ],
                "Objects": [
                    _object(
                        "LabOvenData",
                        "laboven",
                        "synthetic-oven-guid",
                    ),
                    _object(
                        "ChemistryStationData",
                        "chemistrystation",
                        "synthetic-chemistry-guid",
                    ),
                ],
            }
            _create_zip(archive, files)

            snapshot = snapshot_from_zip(archive).to_dict()
            prop = snapshot["properties"][0]
            employee = snapshot["employees"][0]

            self.assertEqual(
                {item["category"] for item in prop["objects"]},
                {"processing"},
            )
            self.assertEqual(employee["role"], "chemist")
            self.assertEqual(employee["assigned_station_count"], 2)
            self.assertTrue(employee["paid_for_today"])


if __name__ == "__main__":
    unittest.main()
