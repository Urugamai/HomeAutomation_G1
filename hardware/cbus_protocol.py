import time
from typing import Dict, Any, Optional, List


class CBusProtocolEngine:
    """Handles low-level Clipsal C-Bus hex/ASCII data calculations and packet decoding."""

    @staticmethod
    def calculate_lrc(hex_str: str) -> str:
        """Calculates the standard C-Bus longitudinal redundancy check (LRC) checksum."""
        try:
            bytes_list = [int(hex_str[i:i + 2], 16) for i in range(0, len(hex_str), 2)]
            total_sum = sum(bytes_list)
            lrc_val = (0x100 - (total_sum % 256)) & 0xFF
            return f"{lrc_val:02X}"
        except Exception:
            return "00"

    @staticmethod
    def parse_text_stream(raw_stream: str, prefixes: list) -> Optional[List[Dict[str, Any]]]:
        """Parses ASCII Text-Hex stream lines into descriptive dictionary records."""
        parsed_messages = []
        fragments = raw_stream.replace("\r", "").split("\n")

        for frag in fragments:
            cleaned = frag.strip().upper().replace("\\", "").replace("/", "").replace("!", "")
            if not cleaned or len(cleaned) < 10 or cleaned.startswith("~~") or cleaned.startswith("A3"):
                continue

            try:
                # =====================================================================
                # 1. PARSE BULK MMI STATUS REPORTS (Starts with 8638... or 0638...)
                # =====================================================================
                if (cleaned.startswith("86") or cleaned.startswith("06")) and cleaned[2:4] == "38":
                    try:
                        start_group_offset = int(cleaned[4:6], 16) * 32
                    except ValueError:
                        start_group_offset = 0

                    payload_hex = cleaned[8:]
                    current_group = start_group_offset

                    for i in range(0, len(payload_hex) - 1, 2):
                        byte_str = payload_hex[i:i + 2]
                        if len(byte_str) < 2 or current_group >= 255:
                            break
                        try:
                            byte_val = int(byte_str, 16)
                        except ValueError:
                            continue

                        for group_shift in range(4):
                            bitmask_pair = (byte_val >> (group_shift * 2)) & 0x03
                            if bitmask_pair == 0x00:
                                state_str = "OFF"
                                val = 0
                            elif bitmask_pair == 0x01:
                                state_str = "ON"
                                val = 100
                            else:
                                current_group += 1
                                continue

                            parsed_messages.append({
                                "application": 56,
                                "group": current_group,
                                "command": state_str,
                                "value": val,
                                "timestamp": time.time()
                            })
                            current_group += 1
                    continue

                # =====================================================================
                # 2. PARSE STANDALONE POINT-TO-POINT COMMANDS (Starts with 05...)
                # =====================================================================
                if cleaned.startswith("05") and (cleaned[4:6] == "38" or cleaned[6:8] == "38"):
                    if cleaned[4:6] == "38":
                        group_hex = cleaned[8:10]
                        cmd_hex = cleaned[10:12] if len(cleaned) >= 12 else "00"
                        action_hex = cleaned[6:8]
                    else:
                        group_hex = cleaned[10:12]
                        cmd_hex = cleaned[12:14] if len(cleaned) >= 14 else "00"
                        action_hex = cleaned[8:10]

                    group_id = int(group_hex, 16)

                    if action_hex == "01" or cmd_hex == "00":
                        state_str = "OFF"
                        val = 0
                    elif action_hex == "79" or cmd_hex == "FF":
                        state_str = "ON"
                        val = 100
                    else:
                        try:
                            raw_val = int(cmd_hex, 16)
                            val = round((raw_val / 255.0) * 100)
                            state_str = "OFF" if val == 0 else "ON"
                        except ValueError:
                            state_str = "OFF"
                            val = 0

                    parsed_messages.append({
                        "application": 56,
                        "group": group_id,
                        "command": state_str,
                        "value": val,
                        "timestamp": time.time()
                    })
            except Exception:
                pass

        return parsed_messages if parsed_messages else None
