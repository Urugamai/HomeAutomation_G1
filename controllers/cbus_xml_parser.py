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

            # Target Application nodes safely
            for app_node in root.findall(".//Application"):
                app_address_node = app_node.find("Address")
                if app_address_node is None or not app_address_node.text:
                    continue

                try:
                    app_id = int(app_address_node.text.strip())
                except ValueError:
                    continue

                if app_id not in app_mappings:
                    continue

                default_type = app_mappings.get(app_id, "light")

                # Process Group nodes underneath this Application safely
                for group_node in app_node.findall(".//Group"):
                    group_address_node = group_node.find("Address")
                    group_tag_node = group_node.find("TagName")

                    if group_address_node is not None and group_tag_node is not None:
                        group_address_str = group_address_node.text
                        tag_name = group_tag_node.text

                        if group_address_str and tag_name:
                            if "unused" in tag_name.lower():
                                continue

                            try:
                                group_id = int(group_address_str.strip())
                            except ValueError:
                                continue

                            # Sanitize naming structures for MQTT stability
                            safe_name = tag_name.strip()
                            safe_name = safe_name.replace(" ", "_").replace("/", "_")
                            safe_name = safe_name.replace("<", "").replace(">", "")

                            name_lower = safe_name.lower()
                            device_type = default_type

                            # Explicit classification hooks matching your exact shorthand
                            if "_b_" in name_lower or "blind" in name_lower:
                                device_type = "blind"
                            elif "_s_" in name_lower or "shutter" in name_lower:
                                device_type = "shutter"
                            elif "dimmer" in name_lower or "_dim_" in name_lower:
                                device_type = "dimmer"

                            devices.append({
                                "name": safe_name,
                                "app": app_id,
                                "group": group_id,
                                "type": device_type
                            })

            print(f"[SUCCESS] Successfully mapped {len(devices)} real nodes from XML.")
            return devices

        except Exception as e:
            print(f"[XML CRITICAL] Ingestion failure: {e}")
            return []
