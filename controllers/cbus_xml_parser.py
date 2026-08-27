import xml.etree.ElementTree as ET
from pathlib import Path


class CBusXMLParser:
    """Handles extraction of tags and groups from Clipsal Toolkit XML files."""

    def __init__(self, xml_path: Path):
        self.xml_path = xml_path

    def parse_devices(self, app_mappings: dict) -> list:
        """Parses the XML file and extracts active C-Bus unit groups."""
        if not self.xml_path.exists():
            print(f"[WARN] C-Bus XML file not found at: {self.xml_path}")
            return []

        devices = []
        try:
            print(f"[PARSING] Processing C-Bus Toolkit file: {self.xml_path}")
            tree = ET.parse(self.xml_path)
            root = tree.getroot()

            # Find all Application blocks in the XML template
            for app_node in root.findall(".//App"):
                app_address_str = app_node.get("GroupAddress")
                if not app_address_str:
                    continue

                app_id = int(app_address_str)

                # Deduce device baseline classification profiles
                default_type = app_mappings.get(app_id, "light")

                # Locate all functional groups mapped under this application
                for group_node in app_node.findall(".//Group"):
                    group_address_str = group_node.get("GroupAddress")
                    tag_name = group_node.get("TagName")

                    if group_address_str and tag_name:
                        group_id = int(group_address_str)

                        # Format tag names to match standard safe MQTT strings
                        safe_name = tag_name.lower().strip()
                        safe_name = safe_name.replace(" ", "_").replace("/", "_")

                        # Identify dimmers based on your label tags
                        device_type = "dimmer" if "dimmer" in safe_name else default_type

                        devices.append({
                            "name": safe_name,
                            "app": app_id,
                            "group": group_id,
                            "type": device_type
                        })

            print(f"[SUCCESS] Parsed {len(devices)} addresses from Toolkit backup.")
            return devices

        except Exception as e:
            print(f"[XML ERROR] Parsing failed unexpectedly: {e}")
            return []
